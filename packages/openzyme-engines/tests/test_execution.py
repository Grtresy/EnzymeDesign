from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from http import client as http_client
import json
from pathlib import Path

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import ArtifactBoundaryService
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SandboxWorkspaceService
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import build_agent_step_context
from openzyme_core import engine_tool_descriptors
from openzyme_core import EngineRegistry
from openzyme_core import ProtocolService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_bio_research_tools
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import RunStatus
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_engines import ExecutionEngine
from openzyme_engines import register_execution_tools
from openzyme_engines.execution import BioArtifactDraft
from openzyme_engines.execution import BioProviderHttpConfig
from openzyme_engines.execution import BioSdkResult
from openzyme_engines.execution import DeterministicBioDatabaseAdapter
from openzyme_engines.execution import DeterministicBioToolsAdapter
from openzyme_engines.execution import _ensure_pipeline_workspace_layout
from openzyme_engines.execution import PreprocessArtifactDraft
from openzyme_engines.execution import PreprocessResult
from openzyme_engines.execution import PipelineSdkFailure
from openzyme_engines.execution import ProviderHttpBioDatabaseAdapter
from openzyme_research import DeterministicBioResearchService
from openzyme_runtime import ToolSideEffect


FPOCKET_EXPECTED_OUTPUTS = [
    {"path": "target_out", "kind": "directory", "format": "fpocket"}
]
VINA_EXPECTED_OUTPUTS = [
    {"path": "outputs/vina_out.pdbqt", "kind": "structure", "format": "pdbqt"}
]
CDHIT_MEMBERSHIP_HEADER = (
    "cluster_id,member_id,representative_id,is_representative,"
    "identity_to_representative,member_length"
)
TOOLCHAIN_RUNTIME_IDENTITY = {
    "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
    "attestation_scope": "same_ssh_login_shell_pre_exec",
    "execution_mode": "ssh",
    "tool_id": "bio_tools.mafft",
    "adapter_id": "bio_tools.mafft",
    "command_template_id": "bio_tools_mafft_sif_v1",
    "runner_contract_digest": "sha256:" + "a" * 64,
    "image_digest": "sha256:" + "b" * 64,
}


@pytest.fixture(autouse=True)
def _isolate_default_execution_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep legacy default-root tests isolated without weakening production guards."""

    original_init = ExecutionEngine.__init__

    def isolated_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("sandbox_workspace_root", tmp_path / "workspaces")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(ExecutionEngine, "__init__", isolated_init)


@pytest.mark.parametrize("symlink_name", (None, "input"))
def test_pipeline_workspace_layout_rejects_symlinks(
    tmp_path: Path,
    symlink_name: str | None,
) -> None:
    workspace_path = tmp_path / "workspace"
    target = tmp_path / "target"
    target.mkdir()
    if symlink_name is None:
        workspace_path.symlink_to(target, target_is_directory=True)
    else:
        workspace_path.mkdir()
        (workspace_path / symlink_name).symlink_to(
            target,
            target_is_directory=True,
        )

    with pytest.raises(OSError):
        _ensure_pipeline_workspace_layout(workspace_path, create=True)

    assert list(target.iterdir()) == []


def test_pipeline_workspace_layout_does_not_repair_existing_missing_directory(
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "workspace"
    _ensure_pipeline_workspace_layout(workspace_path, create=True)
    (workspace_path / "input").rmdir()

    with pytest.raises(OSError):
        _ensure_pipeline_workspace_layout(workspace_path, create=False)

    assert not (workspace_path / "input").exists()


def test_pipeline_workspace_layout_rejects_preexisting_orphan_on_create(
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    orphan = workspace_path / "prior-science.fasta"
    orphan.write_text(">old\nAAAA\n", encoding="utf-8")

    with pytest.raises(OSError):
        _ensure_pipeline_workspace_layout(workspace_path, create=True)

    assert orphan.read_text(encoding="utf-8") == ">old\nAAAA\n"
    assert {item.name for item in workspace_path.iterdir()} == {
        "prior-science.fasta"
    }


def _fpocket_pipeline_code(artifact_id: str = "art_001") -> str:
    return (
        "from openzyme_pipeline import artifacts, hpc, structure_tools\n"
        f"structure = artifacts.get('{artifact_id}')\n"
        "ws = hpc.workspace('fpocket')\n"
        "remote_structure = ws.stage_artifact(structure['artifact_id'], workspace_path='inputs/structure.pdb')\n"
        f"run = structure_tools.fpocket(structure=remote_structure, placement=ws, expected_outputs={FPOCKET_EXPECTED_OUTPUTS!r})\n"
        "ws.fetch_outputs(run)\n"
    )


def _call_fpocket(control_handler, artifact_id: str = "art_001") -> dict[str, object]:  # type: ignore[no-untyped-def]
    ws = dict(control_handler("hpc.workspace", {"label": "fpocket"}))
    remote_structure = dict(
        control_handler(
            "hpc.stage_artifact",
            {
                "hpc_workspace": ws,
                "artifact_id": artifact_id,
                "workspace_path": "inputs/structure.pdb",
            },
        )
    )
    run = dict(
        control_handler(
            "structure_tools.fpocket",
            {
                "structure": remote_structure,
                "placement": ws,
                "expected_outputs": FPOCKET_EXPECTED_OUTPUTS,
                "params": {},
            },
        )
    )
    return dict(
        control_handler(
            "hpc.fetch_outputs", {"hpc_workspace": ws, "run_id": run["run_id"]}
        )
    )


def _call_vina(control_handler, artifact_id: str = "art_001") -> dict[str, object]:  # type: ignore[no-untyped-def]
    ws = dict(control_handler("hpc.workspace", {"label": "vina"}))
    receptor = dict(
        control_handler(
            "hpc.stage_artifact",
            {
                "hpc_workspace": ws,
                "artifact_id": artifact_id,
                "workspace_path": "inputs/receptor.pdbqt",
            },
        )
    )
    ligand = dict(
        control_handler(
            "hpc.stage_artifact",
            {
                "hpc_workspace": ws,
                "artifact_id": artifact_id,
                "workspace_path": "inputs/ligand.pdbqt",
            },
        )
    )
    return dict(
        control_handler(
            "docking.vina",
            {
                "receptor": receptor,
                "ligand": ligand,
                "placement": ws,
                "expected_outputs": VINA_EXPECTED_OUTPUTS,
                "params": {},
            },
        )
    )


def _content_digest(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _payload_digest(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _artifact_digest(repositories: CoreRepositories, artifact_id: str) -> str:
    artifact = repositories.artifacts.get(artifact_id)
    assert artifact is not None
    metadata = dict(artifact.metadata or {})
    digest = metadata.get("content_digest") or metadata.get("tree_digest")
    assert digest
    return str(digest)


def _workspace_payload(label: str = "aox_hmm") -> dict[str, object]:
    return {
        "kind": "hpc_workspace",
        "hpc_workspace_id": f"hpcws_test_{label}",
        "label": label,
        "normalized_label": label,
    }


def _stage_payload(
    repositories: CoreRepositories,
    artifact_id: str,
    workspace: dict[str, object],
    path: str,
) -> dict[str, object]:
    return {
        "kind": "hpc_stage_ref",
        "stage_ref_id": f"stage_{artifact_id}_{path.replace('/', '_')}",
        "hpc_workspace_id": workspace["hpc_workspace_id"],
        "artifact_id": artifact_id,
        "artifact_digest": _artifact_digest(repositories, artifact_id),
        "workspace_relative_path": path,
    }


def _bio_tool_outputs(method: str) -> list[dict[str, str]]:
    return {
        "bio_tools.cdhit": [
            {
                "path": "bio_tools/cdhit/clustered.fasta",
                "kind": "sequence",
                "format": "fasta",
            },
            {"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"},
        ],
        "bio_tools.mafft": [
            {
                "path": "bio_tools/mafft/alignment.fasta",
                "kind": "sequence",
                "format": "fasta",
            }
        ],
        "bio_tools.hmmbuild": [
            {
                "path": "bio_tools/hmmbuild/model.hmm",
                "kind": "result",
                "format": "hmm",
            }
        ],
        "bio_tools.hmmalign": [
            {
                "path": "bio_tools/hmmalign/aligned.fasta",
                "kind": "sequence",
                "format": "fasta",
            }
        ],
        "bio_tools.hmmer_search_cli": [
            {
                "path": "bio_tools/hmmer_search_cli/hits.csv",
                "kind": "result",
                "format": "csv",
            },
            {
                "path": "bio_tools/hmmer_search_cli/tool.log",
                "kind": "log",
                "format": "txt",
            },
        ],
    }[method]


def _runner_output_content(relative_path: str) -> str:
    if relative_path.endswith(".hmm"):
        return "HMMER3/f [runner]\nNAME runner_model\n//\n"
    if relative_path.endswith("/clusters.csv"):
        return (
            f"{CDHIT_MEMBERSHIP_HEADER}\n"
            "cluster_0,seq1,seq1,true,1.000000,22\n"
            "cluster_0,seq2,seq1,false,0.900000,22\n"
        )
    if relative_path.endswith("/hits.csv"):
        return "target,accession,evalue,score\nseq1,seq1,1e-20,100.0\n"
    if relative_path.endswith((".fasta", ".fa", ".faa", ".afa")):
        return ">seq1\nMKTAYIAKQRQISFVKSHFSRQ\n>seq2\nMKADKSELVQKAKLAEQAERYD\n"
    if relative_path.endswith(".log"):
        return "runner completed\n"
    return "runner output\n"


class ImmediateSuccessRunner:
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        expected_outputs = list(
            (dict(payload.get("runspec") or {}).get("expected_outputs") or [])
        )
        runspec = dict(payload.get("runspec") or {})
        run_suffix = hashlib.sha256(
            json.dumps(
                {
                    "name": runspec.get("name"),
                    "expected_outputs": expected_outputs,
                    "inputs": runspec.get("inputs"),
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:8]
        refs = []
        for output in expected_outputs or [{"path": "stdout.log"}]:
            relative_path = str(dict(output).get("path") or "stdout.log")
            kind = (
                ArtifactKind.LOG
                if relative_path.endswith(".log")
                else ArtifactKind.RESULT
            )
            if relative_path.endswith((".pdb", ".pdbqt", ".sdf", ".mol2", ".cif")):
                kind = ArtifactKind.STRUCTURE
            storage_path = Path("/tmp/openzyme-test-runner") / relative_path
            if dict(output).get("kind") in {"dir", "directory"}:
                storage_path.mkdir(parents=True, exist_ok=True)
                (storage_path / "summary.txt").write_text(
                    "runner directory output\n", encoding="utf-8"
                )
                if (
                    relative_path == "target_out"
                    or dict(output).get("format") == "fpocket"
                ):
                    (storage_path / "target_info.txt").write_text(
                        "Pocket 1 :\n\tScore : \t0.928\n\tVolume : \t1006.516\n\n"
                        "Pocket 2 :\n\tScore : \t0.215\n\tVolume : \t326.310\n",
                        encoding="utf-8",
                    )
            else:
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                storage_path.write_text(
                    _runner_output_content(relative_path), encoding="utf-8"
                )
            refs.append(
                ExecutionArtifactRef(
                    storage_uri=str(storage_path),
                    relative_path=relative_path,
                    kind=kind,
                )
            )
        return ExecutionOutcome(
            run_id=f"runner_run_{run_suffix}",
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir=f"/remote/run_{run_suffix}",
            raw_result={"pockets_found": 2},
            artifacts=tuple(refs),
        )

    def get_execution_status(self, *, run_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "status polling should not be used for immediate execution"
        )

    def fetch_execution_artifacts(self, *, run_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError("fetch should not be used for immediate execution")

    def cancel_execution(self, *, run_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError("cancel should not be used in this test")


class BackgroundRunner:
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, payload
        return ExecutionOutcome(
            run_id="runner_job_123",
            status=RunStatus.QUEUED,
            execution_mode="sbatch",
            remote_run_dir="opaque://runner_job_123",
            raw_result={"submitted": True},
        )

    def get_execution_status(self, *, run_id: str):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionStatusSnapshot

        return ExecutionStatusSnapshot(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            raw_result={"state": "completed", "pockets_found": 1},
            exit_code=0,
        )

    def fetch_execution_artifacts(self, *, run_id: str):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        relative_path = "target_out"
        return ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            execution_mode="sbatch",
            remote_run_dir=f"opaque://{run_id}",
            raw_result={"pockets_found": 1},
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri=f"/tmp/{relative_path}",
                    relative_path=relative_path,
                    kind=ArtifactKind.RESULT,
                ),
            ),
            exit_code=0,
        )

    def cancel_execution(self, *, run_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError("cancel should not be used in this test")


class CapturingSuccessRunner(ImmediateSuccessRunner):
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        self.payloads.append(payload)
        return super().submit_execution(session_id, payload)


class ToolchainIdentitySuccessRunner(ImmediateSuccessRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        outcome = super().submit_execution(session_id, payload)
        unsafe_identity = {
            **TOOLCHAIN_RUNTIME_IDENTITY,
            "sif_path": "/private/tool.sif",
            "command": ["apptainer", "exec", "/private/tool.sif"],
            "secret": "must-not-propagate",
        }
        return ExecutionOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            raw_result={
                **outcome.raw_result,
                "toolchain_runtime_identity": unsafe_identity,
            },
            artifacts=outcome.artifacts,
            exit_code=outcome.exit_code,
            toolchain_runtime_identity=unsafe_identity,  # type: ignore[arg-type]
        )

    def submit_reserved_execution(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        run_id: str,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        outcome = self.submit_execution(session_id, payload)
        self.reserved_run_id = run_id
        return ExecutionOutcome(
            run_id=run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=f"opaque://{run_id}",
            raw_result=outcome.raw_result,
            artifacts=outcome.artifacts,
            exit_code=outcome.exit_code,
            toolchain_runtime_identity=outcome.toolchain_runtime_identity,
        )


def test_toolchain_runtime_identity_projection_is_ssh_only() -> None:
    from openzyme_engines.execution import _project_toolchain_runtime_identity

    assert (
        _project_toolchain_runtime_identity(
            TOOLCHAIN_RUNTIME_IDENTITY,
            execution_mode="sbatch",
        )
        is None
    )


class AdapterShapeArtifactRef:
    def __init__(
        self, *, storage_uri: str, relative_path: str, kind: ArtifactKind
    ) -> None:
        self.storage_uri = storage_uri
        self.relative_path = relative_path
        self.kind = kind


class AdapterShapeSuccessRunner(ImmediateSuccessRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        outcome = super().submit_execution(session_id, payload)
        return ExecutionOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            raw_result=outcome.raw_result,
            artifacts=tuple(
                AdapterShapeArtifactRef(
                    storage_uri=artifact.storage_uri,
                    relative_path=artifact.relative_path,
                    kind=artifact.kind,
                )
                for artifact in outcome.artifacts
            ),
            exit_code=outcome.exit_code,
        )


class CapturingFailedRunner(ImmediateSuccessRunner):
    def __init__(self, partial_artifact_path: Path | None = None) -> None:
        self.payloads: list[dict[str, object]] = []
        self.partial_artifact_path = partial_artifact_path

    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        self.payloads.append(payload)
        artifacts = ()
        raw_artifacts: dict[str, str] = {}
        if self.partial_artifact_path is not None:
            self.partial_artifact_path.write_text(
                ">partial\nNOT_VALIDATED\n",
                encoding="utf-8",
            )
            artifacts = (
                ExecutionArtifactRef(
                    storage_uri=str(self.partial_artifact_path),
                    relative_path="target_out",
                    kind=ArtifactKind.RESULT,
                ),
            )
            raw_artifacts = {"target_out": str(self.partial_artifact_path)}
        return ExecutionOutcome(
            run_id="runner_failed_001",
            status=RunStatus.FAILED,
            execution_mode="ssh",
            remote_run_dir="/remote/run_failed",
            raw_result={
                "status": "failed",
                "exit_code": 127,
                "error_code": "APPTAINER_MISSING",
                "stdout": "",
                "stderr": "apptainer: command not found",
                "artifacts": raw_artifacts,
            },
            artifacts=artifacts,
            exit_code=127,
        )


class MissingDeclaredOutputRunner(CapturingSuccessRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        outcome = super().submit_execution(session_id, payload)
        return ExecutionOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            raw_result=outcome.raw_result,
            artifacts=outcome.artifacts[:1],
            exit_code=outcome.exit_code,
        )


class CdhitMembershipOutputRunner(CapturingSuccessRunner):
    def __init__(self, membership_content: str) -> None:
        super().__init__()
        self.membership_content = membership_content

    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        outcome = super().submit_execution(session_id, payload)
        membership_artifact = next(
            artifact
            for artifact in outcome.artifacts
            if artifact.relative_path.endswith("/clusters.csv")
        )
        Path(membership_artifact.storage_uri).write_text(
            self.membership_content,
            encoding="utf-8",
        )
        return outcome


class MissingAllDeclaredOutputsRunner(CapturingSuccessRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        outcome = super().submit_execution(session_id, payload)
        return ExecutionOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            raw_result=outcome.raw_result,
            artifacts=(),
            exit_code=outcome.exit_code,
        )


class ExplicitNonCutoverFixtureRunner(CapturingSuccessRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        outcome = super().submit_execution(session_id, payload)
        return ExecutionOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            execution_mode="fixture_non_cutover",
            remote_run_dir=outcome.remote_run_dir,
            raw_result={"fixture": True, "pockets_found": 0},
            artifacts=(),
            exit_code=outcome.exit_code,
        )


class CountingBioFixtureAdapter(DeterministicBioDatabaseAdapter):
    def __init__(self) -> None:
        self.ncbi_calls = 0

    def ncbi_fetch_proteins(self, **kwargs):  # type: ignore[no-untyped-def]
        self.ncbi_calls += 1
        return super().ncbi_fetch_proteins(**kwargs)


class RecordingUniprotFixtureAdapter(DeterministicBioDatabaseAdapter):
    def __init__(self) -> None:
        self.batch_sizes: list[int | None] = []

    def uniprot_fetch(self, **kwargs):  # type: ignore[no-untyped-def]
        self.batch_sizes.append(kwargs["batch_size"])
        return super().uniprot_fetch(**kwargs)


class CapturingTimeoutRunner(CapturingFailedRunner):
    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        self.payloads.append(payload)
        return ExecutionOutcome(
            run_id="runner_timeout_001",
            status=RunStatus.FAILED,
            execution_mode="ssh",
            remote_run_dir="/remote/run_timeout",
            raw_result={
                "status": "failed",
                "exit_code": 124,
                "error_code": "COMMAND_TIMEOUT",
                "stage": "remote_execution",
                "stdout": "",
                "stderr": "Command timed out after 7200 seconds",
            },
            artifacts=(),
            exit_code=124,
        )


class CapturingTransportFailedRunner(CapturingFailedRunner):
    def __init__(self, error_code: str) -> None:
        super().__init__()
        self.error_code = error_code

    def submit_execution(self, session_id: str, payload: dict[str, object]):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id
        self.payloads.append(payload)
        return ExecutionOutcome(
            run_id="runner_transport_failed_001",
            status=RunStatus.FAILED,
            execution_mode="ssh",
            remote_run_dir="opaque://runner_transport_failed_001",
            raw_result={
                "status": "failed",
                "exit_code": 255,
                "error_code": self.error_code,
                "stage": "remote_execution",
                "stdout": "",
                "stderr": "trusted runner transport unavailable",
            },
            artifacts=(),
            exit_code=255,
        )


class RaisingTypedStagingRunner:
    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ):  # type: ignore[no-untyped-def]
        from mcp_hpc_runner.errors import HpcStagingFailure

        del session_id, payload
        raise HpcStagingFailure(
            phase="input_transfer",
            run_id="opaque_runner_123",
            input_ordinal=2,
            content_digest="sha256:" + "a" * 64,
            returncode=124,
            timed_out=True,
            elapsed_seconds=120.125,
        )


class MalformedStagingDiagnostic(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "runner failed at alice@private-hpc:~/secret "
            "credential=must-not-cross /home/alice/private/input.fasta"
        )

    def to_safe_diagnostic(self) -> dict[str, object]:
        return {
            "schema_id": "runner_failure@1",
            "phase": "input_transfer",
            "run_id": "opaque_runner_456",
            "input_ordinal": 1,
            "content_digest": "sha256:" + "b" * 64,
            "returncode": 1,
            "timed_out": False,
            "elapsed_seconds": 0.5,
            "remote_path": "/private/runner/input.fasta",
        }


class RaisingMalformedStagingRunner:
    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ):  # type: ignore[no-untyped-def]
        del session_id, payload
        raise MalformedStagingDiagnostic()


class ThrowingStagingDiagnostic(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "alice@private-hpc:~/secret credential=must-not-cross "
            "/home/alice/private/input.fasta"
        )

    def to_safe_diagnostic(self) -> dict[str, object]:
        raise RuntimeError(
            "projector saw alice@private-hpc:~/secret credential=must-not-cross"
        )


class RaisingThrowingStagingRunner:
    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ):  # type: ignore[no-untyped-def]
        del session_id, payload
        raise ThrowingStagingDiagnostic()


class RaisingLegacyStagingRunner:
    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ):  # type: ignore[no-untyped-def]
        del session_id, payload
        raise RuntimeError("runner failed at /home/alice/private/input.fasta")


class SandboxPreflight:
    def __init__(
        self,
        ok: bool,
        message: str = "ok",
        runtime_identity: dict[str, str] | None = None,
    ) -> None:
        self.ok = ok
        self.message = message
        self.runtime_identity = runtime_identity


def _test_sandbox_runtime_identity(*, suffix: str = "base") -> dict[str, str]:
    identity = {
        "configured_image_ref": "openzyme-pipeline-sandbox:test",
        "immutable_image_ref": "sha256:"
        + hashlib.sha256(f"image:{suffix}".encode()).hexdigest(),
        "image_digest": "sha256:"
        + hashlib.sha256(f"image:{suffix}".encode()).hexdigest(),
        "pipeline_sdk_digest": "sha256:"
        + hashlib.sha256(f"sdk:{suffix}".encode()).hexdigest(),
        "sandbox_protocol_version": "test.v1",
    }
    identity["runtime_identity_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return identity


class FakeHttpResponse:
    def __init__(
        self, *, status: int = 200, headers: dict[str, str] | None = None, body: str
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body.encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self) -> bytes:
        return self._body


class HandlerSandboxRunner:
    def __init__(self, *, preflight_ok: bool = True) -> None:
        self.preflight_ok = preflight_ok
        self.calls = 0

    def preflight(self) -> SandboxPreflight:
        return SandboxPreflight(
            self.preflight_ok,
            "podman missing",
            _test_sandbox_runtime_identity(),
        )

    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        assert expected_runtime_identity == _test_sandbox_runtime_identity()
        self.calls += 1
        if control_handler is not None:
            _call_fpocket(control_handler)
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(),
        )


class DriftingIdentitySandboxRunner(HandlerSandboxRunner):
    def __init__(self) -> None:
        super().__init__()
        self.preflight_calls = 0

    def preflight(self) -> SandboxPreflight:
        self.preflight_calls += 1
        suffix = "approved" if self.preflight_calls == 1 else "drifted"
        return SandboxPreflight(
            True, runtime_identity=_test_sandbox_runtime_identity(suffix=suffix)
        )


class BioSandboxRunner:
    def __init__(self, operations: tuple[tuple[str, dict[str, object]], ...]) -> None:
        self.operations = operations
        self.results: list[dict[str, object]] = []
        self.calls = 0

    def preflight(self) -> SandboxPreflight:
        return SandboxPreflight(True, runtime_identity=_test_sandbox_runtime_identity())

    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        assert expected_runtime_identity == _test_sandbox_runtime_identity()
        self.calls += 1
        if control_handler is not None:
            for method, params in self.operations:
                self.results.append(dict(control_handler(method, params)))
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(),
        )


class FetchAfterBioToolSandboxRunner(BioSandboxRunner):
    def __init__(
        self, operation: tuple[str, dict[str, object]], workspace: dict[str, object]
    ) -> None:
        super().__init__((operation,))
        self.workspace = workspace

    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        assert expected_runtime_identity == _test_sandbox_runtime_identity()
        self.calls += 1
        if control_handler is not None:
            method, params = self.operations[0]
            run = dict(control_handler(method, params))
            self.results.append(run)
            self.results.append(
                dict(
                    control_handler(
                        "hpc.fetch_outputs",
                        {"hpc_workspace": self.workspace, "run_id": str(run["run_id"])},
                    )
                )
            )
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(),
        )


class FetchAfterEachBioToolSandboxRunner(BioSandboxRunner):
    def __init__(
        self,
        operations: tuple[tuple[str, dict[str, object]], ...],
        workspace: dict[str, object],
    ) -> None:
        super().__init__(operations)
        self.workspace = workspace

    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        assert expected_runtime_identity == _test_sandbox_runtime_identity()
        self.calls += 1
        if control_handler is not None:
            for method, params in self.operations:
                run = dict(control_handler(method, params))
                self.results.append(run)
                self.results.append(
                    dict(
                        control_handler(
                            "hpc.fetch_outputs",
                            {
                                "hpc_workspace": self.workspace,
                                "run_id": str(run["run_id"]),
                            },
                        )
                    )
                )
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(),
        )


class FailedHpcSandboxRunner(HandlerSandboxRunner):
    def __init__(self, stderr_path: Path) -> None:
        super().__init__()
        self.stderr_path = stderr_path

    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionArtifactRef
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, code, inputs
        assert expected_runtime_identity == _test_sandbox_runtime_identity()
        self.calls += 1
        if control_handler is not None:
            _call_fpocket(control_handler)
        self.stderr_path.write_text(
            "openzyme_pipeline.client.PipelineSdkError: "
            f"structure_tools.fpocket failed with status failed for run run_{invocation_id}_1",
            encoding="utf-8",
        )
        partial_result_path = self.stderr_path.with_name("partial-result.fasta")
        partial_result_path.write_text(
            ">partial\nNOT_VALIDATED\n",
            encoding="utf-8",
        )
        return ExecutionOutcome(
            run_id=f"sandbox_{invocation_id}",
            status=RunStatus.FAILED,
            execution_mode="podman",
            remote_run_dir=f"podman://{invocation_id}",
            raw_result={"registered_artifact_count": 0},
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri=str(self.stderr_path),
                    relative_path="logs/stderr.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri=str(partial_result_path),
                    relative_path="bio_tools/mafft/alignment.fasta",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            exit_code=1,
        )


class UnplannedHpcSandboxRunner(HandlerSandboxRunner):
    def run_pipeline(
        self,
        *,
        session_id,
        invocation_id,
        code,
        inputs=(),
        control_handler=None,
        expected_runtime_identity=None,
    ):  # type: ignore[no-untyped-def]
        from openzyme_engines.execution import ExecutionOutcome

        del session_id, invocation_id, code, inputs
        assert expected_runtime_identity == _test_sandbox_runtime_identity()
        self.calls += 1
        if control_handler is not None:
            _call_vina(control_handler)
        return ExecutionOutcome(
            run_id="sandbox_unplanned",
            status=RunStatus.SUCCEEDED,
            execution_mode="podman",
            remote_run_dir="podman://unplanned",
            raw_result={},
            artifacts=(),
        )


class FakeVinaPreprocessAdapter:
    def preprocess_for_execution(
        self,
        *,
        session_id: str,
        invocation_id: str,
        handoff,
        required_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> PreprocessResult:
        del session_id, handoff
        return PreprocessResult(
            required_artifacts=required_artifacts,
            created_artifacts=(
                PreprocessArtifactDraft(
                    source_artifact_id="art_001",
                    operation="prepare_receptor",
                    storage_uri="/tmp/preprocess/receptor.pdbqt",
                    relative_path=f"preprocess/{invocation_id}/receptor.pdbqt",
                    input_format="pdb",
                    output_format="pdbqt",
                    tool="fake-preprocess",
                    metadata={"fake": True},
                ),
            ),
        )


class InjectingCompiler:
    def compile_request(
        self, *, handoff, task, resolved_required_artifacts, resolved_context_artifacts
    ):  # type: ignore[no-untyped-def]
        del handoff, task, resolved_required_artifacts, resolved_context_artifacts
        return {
            "tool_name": "exec.run",
            "runspec": {
                "name": "bad",
                "stage": "execution",
                "command": ["cat", "/work/input.pdb"],
                "inputs": [
                    {
                        "artifact_id": "art_001",
                        "local_path": "/etc/passwd",
                        "remote_path": "input.pdb",
                    }
                ],
                "expected_outputs": [],
                "metadata": {},
            },
        }


def _valid_test_pdb(residue_count: int = 10, atoms_per_residue: int = 5) -> str:
    lines: list[str] = []
    serial = 1
    atom_names = ("N", "CA", "C", "O", "CB")
    for residue_index in range(1, residue_count + 1):
        for atom_index in range(atoms_per_residue):
            atom_name = atom_names[atom_index % len(atom_names)]
            lines.append(
                f"ATOM  {serial:5d} {atom_name:<4} ALA A{residue_index:4d}    "
                f"{float(residue_index):8.3f}{float(atom_index):8.3f}{0.0:8.3f}  1.00 20.00           C"
            )
            serial += 1
    lines.append("END")
    return "\n".join(lines) + "\n"


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    input_structure = _valid_test_pdb()
    Path("/tmp/input_structure.pdb").write_text(input_structure, encoding="utf-8")
    ligand_content = "REMARK fixture ligand\n"
    Path("/tmp/ligand.pdbqt").write_text(ligand_content, encoding="utf-8")
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Execution",
        objective="Run execution engine",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-20T12:00:00+00:00",
        updated_at="2026-04-20T12:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name="wt/analysis",
            claimed_ref="agent:planner",
            created_at="2026-04-20T12:00:01+00:00",
            updated_at="2026-04-20T12:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Execute fpocket",
            description="Evaluate the focused structure.",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="execution",
            assigned_ref="agent:planner",
            created_at="2026-04-20T12:00:02+00:00",
            updated_at="2026-04-20T12:00:02+00:00",
            lane_id="lane_001",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="seed_invocation",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="seed",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="seed:artifact",
            started_at="2026-04-20T12:00:02+00:00",
            finished_at="2026-04-20T12:00:03+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/input_structure.pdb",
            relative_path="input_structure.pdb",
            title="input_structure.pdb",
            description=None,
            metadata={
                "source": "seed",
                "format": "pdb",
                "content_digest": _content_digest(input_structure),
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_002",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/ligand.pdbqt",
            relative_path="ligand.pdbqt",
            title="ligand.pdbqt",
            description=None,
            metadata={
                "source": "seed",
                "format": "pdbqt",
                "content_digest": _content_digest(ligand_content),
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )
    return session


def _save_pipeline_source(
    repositories: CoreRepositories,
    *,
    artifact_id: str,
    code: str,
    session_id: str = "sess_001",
    task_id: str = "task_001",
    lane_id: str = "lane_001",
) -> str:
    source_path = Path(f"/tmp/{artifact_id}.py")
    source_path.write_text(code, encoding="utf-8")
    source_digest = f"sha256:{hashlib.sha256(code.encode('utf-8')).hexdigest()}"
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=lane_id,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.CODE,
            storage_uri=str(source_path),
            relative_path=f"code/{artifact_id}/v1/{artifact_id}/pipeline.py",
            title="pipeline.py",
            description=None,
            metadata={
                "format": "python",
                "semantic_type": "pipeline_source",
                "content_digest": source_digest,
                "lineage_root_artifact_id": artifact_id,
                "version": 1,
            },
            created_at="2026-04-20T12:00:04+00:00",
        )
    )
    return artifact_id


def _pipeline_source_id(
    repositories: CoreRepositories, artifact_id: str, code: str
) -> str:
    return _save_pipeline_source(repositories, artifact_id=artifact_id, code=code)


def _executor_step(context: SessionRuntimeContext):
    context.agent_id = "agent:executor"
    context.actor_kind = "teammate"
    context.actor_role = "executor"
    router = context.tool_registry.to_tool_router(context)
    step_context = build_agent_step_context(context, call_index=1)
    return router, step_context


def _save_hmm_artifact(
    repositories: CoreRepositories, artifact_id: str = "art_hmm_001"
) -> str:
    content = "HMMER3/f [fixture]\nNAME fixture\n//\n"
    hmm_path = Path(f"/tmp/{artifact_id}.hmm")
    hmm_path.write_text(content, encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id="sess_001",
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri=str(hmm_path),
            relative_path=f"hmms/{artifact_id}.hmm",
            title=f"{artifact_id}.hmm",
            description=None,
            metadata={
                "source": "seed",
                "format": "hmm",
                "content_digest": _content_digest(content),
            },
            created_at="2026-04-20T12:00:04+00:00",
        )
    )
    return artifact_id


def _save_fasta_artifact(
    repositories: CoreRepositories, artifact_id: str = "art_fasta_001"
) -> str:
    content = ">seq1\nMKTAYIAKQRQISFVKSHFSRQ\n>seq2\nMKADKSELVQKAKLAEQAERYD\n"
    fasta_path = Path(f"/tmp/{artifact_id}.fasta")
    fasta_path.write_text(content, encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id="sess_001",
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.SEQUENCE,
            storage_uri=str(fasta_path),
            relative_path=f"sequences/{artifact_id}.fasta",
            title=f"{artifact_id}.fasta",
            description=None,
            metadata={
                "source": "seed",
                "format": "fasta",
                "content_digest": _content_digest(content),
            },
            created_at="2026-04-20T12:00:04+00:00",
        )
    )
    return artifact_id


def _seed_sandbox_adapter_workspace(
    repositories: CoreRepositories,
    *,
    workspace_root: Path,
    sandbox_workspace_id: str = "sws_adapter_001",
) -> str:
    source_root = Path("/tmp/art_source_snapshot")
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "pipeline.py").write_text(
        "from openzyme_pipeline import bio_tools\n", encoding="utf-8"
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_source_snapshot",
            session_id="sess_001",
            task_id="task_001",
            lane_id="lane_001",
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.CODE,
            storage_uri=str(source_root),
            relative_path="code/sws_adapter_001/source",
            title="source snapshot",
            description="Sandbox source tree snapshot",
            metadata={
                "semantic_type": "pipeline_source_snapshot",
                "format": "source_tree",
                "sandbox_workspace_id": sandbox_workspace_id,
                "source_tree_digest": "sha256:source",
            },
            created_at="2026-04-20T12:00:05+00:00",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:sandbox-adapter",
            session_id="sess_001",
            lane_id="lane_001",
            task_id="task_001",
            name="Sandbox adapter",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-04-20T12:00:05+00:00",
            updated_at="2026-04-20T12:00:05+00:00",
            idle_since="2026-04-20T12:00:05+00:00",
            member_id="member_sandbox_adapter",
        )
    )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id=sandbox_workspace_id,
            session_id="sess_001",
            agent_member_id="member_sandbox_adapter",
            agent_id="agent:sandbox-adapter",
            focus_task_id="task_001",
            focus_lane_id="lane_001",
            status=SandboxWorkspaceStatus.READY,
            image_ref="openzyme-pipeline-sandbox:s15-test",
            image_digest="sha256:s15-test",
            image_version="s15-test",
            sandbox_protocol_version="s15",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="s15.workspace_manifest.v1",
            volume_digest="",
            quota_summary={},
            directory_summary={},
            materialized_input_artifact_ids=(),
            registered_artifact_ids=(),
            source_code_artifact_ids=("art_source_snapshot",),
            created_at="2026-04-20T12:00:05+00:00",
            last_attached_at="2026-04-20T12:00:05+00:00",
        )
    )
    _ensure_pipeline_workspace_layout(
        workspace_root / sandbox_workspace_id,
        create=True,
    )
    return sandbox_workspace_id


def _seed_sandbox_adapter_run(
    repositories: CoreRepositories,
    *,
    sandbox_workspace_id: str,
    sandbox_run_id: str,
) -> None:
    workspace = repositories.sandbox_workspaces.get(sandbox_workspace_id)
    assert workspace is not None
    assert workspace.source_code_artifact_ids
    source_snapshot_artifact_id = workspace.source_code_artifact_ids[-1]
    source_snapshot = repositories.artifacts.get(source_snapshot_artifact_id)
    assert source_snapshot is not None
    runtime_identity = {
        "configured_image_ref": workspace.image_ref,
        "immutable_image_ref": workspace.image_digest,
        "image_digest": workspace.image_digest,
        "pipeline_sdk_digest": "sha256:" + hashlib.sha256(b"adapter-sdk").hexdigest(),
        "sandbox_protocol_version": workspace.sandbox_protocol_version,
    }
    runtime_identity["runtime_identity_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(runtime_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id=sandbox_run_id,
            session_id="sess_001",
            sandbox_workspace_id=sandbox_workspace_id,
            agent_id=workspace.agent_id,
            task_id="task_001",
            lane_id="lane_001",
            argv=("python", "/workspace/src/pipeline.py"),
            argv_digest="sha256:adapter-argv",
            cwd="/workspace",
            env_digest="sha256:adapter-env",
            status=SandboxRunStatus.RUNNING,
            source_snapshot_artifact_id=source_snapshot_artifact_id,
            source_tree_digest=str(
                dict(source_snapshot.metadata or {}).get("source_tree_digest")
                or "sha256:source"
            ),
            changed_files_summary={},
            compatibility=runtime_identity,
            created_at="2026-04-20T12:00:06+00:00",
            updated_at="2026-04-20T12:00:06+00:00",
            started_at="2026-04-20T12:00:06+00:00",
        )
    )


def _sandbox_uniprot_operation(
    *,
    sandbox_workspace_id: str,
    sandbox_run_id: str,
    params: dict[str, object],
    operation_id: str = "op_sandbox_uniprot",
) -> ControlledOperation:
    return ControlledOperation(
        operation_id=operation_id,
        session_id="sess_001",
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id=sandbox_run_id,
        logical_operation_key="bio.uniprot_fetch",
        operation_digest="sha256:" + hashlib.sha256(operation_id.encode()).hexdigest(),
        params_digest=_payload_digest(params),
        backend_category="provider_http",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-07-20T00:00:01+00:00",
        updated_at="2026-07-20T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_id=f"appr_{operation_id}",
        approval_state="approved",
        route_reason="static_policy:v1",
        source_snapshot_artifact_id="art_source_snapshot",
        source_snapshot_digest="sha256:source",
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio",
        function_name="uniprot_fetch",
        route_policy_id="bio.uniprot_fetch.provider:v1",
        placement="provider",
        selected_backend="provider_http",
        resource_class="network_io",
        runtime_packaging_id="provider_http:v1",
        provider_config_digest="provider_config:uniprot:v1",
        expected_outputs_summary={"output_dir": params["output_dir"]},
        resource_estimate={"network_io": True},
        idempotency_key="bio.uniprot_fetch:" + _payload_digest(params),
    )


def _approve_request(repositories: CoreRepositories, approval: ApprovalRequest) -> None:
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )


def test_execution_engine_waits_for_approval_before_submitting() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    started = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_001",
    )

    assert started.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert started.approval is not None
    assert (
        repositories.runs.list_by_invocation(session.session_id, "inv_exec_001") == []
    )


def test_execution_engine_resumes_after_approval_and_persists_run_and_artifacts() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_001",
    )
    approval = first.approval
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=approval.request_ref,
            resolution_ref="artifact://approvals/appr_001-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:00:04+00:00",
        )
    )

    resumed = engine.continue_after_approval(
        invocation_id="inv_exec_001", resolution="Approved for launch."
    )

    assert resumed.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert resumed.run is not None
    assert resumed.run.status is RunStatus.SUCCEEDED
    assert resumed.run.summary == "fpocket found 2 pocket(s); top pocket score 0.928."
    assert resumed.parsed_result is not None
    assert (
        resumed.parsed_result.result_summary
        == "fpocket found 2 pocket(s); top pocket score 0.928."
    )
    assert resumed.artifacts[0].artifact_id == "run_inv_exec_001:target_out"
    payload = resumed.to_dict()
    assert payload["run"]["summary"] == payload["parsed_result"]["result_summary"]
    assert payload["artifacts"]
    assert (
        repositories.runs.get_by_invocation(session.session_id, "inv_exec_001").summary
        is not None
    )


def test_execution_engine_never_persists_failed_partial_scientific_artifacts(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    partial_path = tmp_path / "partial-target-out"
    engine = ExecutionEngine(
        repositories,
        CapturingFailedRunner(partial_artifact_path=partial_path),
    )
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_failed_partial",
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)

    resumed = engine.continue_after_approval(
        invocation_id="inv_exec_failed_partial",
        resolution="Approved for launch.",
    )

    assert resumed.invocation.status is EngineInvocationStatus.FAILED
    assert resumed.artifacts == ()
    assert repositories.artifacts.list_by_invocation(
        session.session_id,
        "inv_exec_failed_partial",
    ) == []
    output = repositories.engine_documents.get(str(resumed.invocation.output_ref))
    assert output is not None
    assert output.payload["outcome"]["artifacts"] == []
    assert output.payload["outcome"]["raw_result"]["artifacts"] == {}
    assert str(partial_path) not in str(output.payload)


def test_execution_engine_resume_keeps_pending_approval_waiting() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_pending_resume",
    )

    resumed = engine.continue_after_approval(
        invocation_id="inv_exec_pending_resume",
        resolution="Attempted direct resume.",
    )

    assert first.approval is not None
    assert resumed.approval is not None
    assert resumed.approval.status is ApprovalRequestStatus.PENDING
    assert resumed.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert (
        repositories.invocations.get("inv_exec_pending_resume").status
        is EngineInvocationStatus.WAITING_APPROVAL
    )
    assert (
        repositories.runs.list_by_invocation(
            session.session_id, "inv_exec_pending_resume"
        )
        == []
    )


def test_execution_engine_resume_cancels_rejected_approval() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    first = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": True,
        },
        invocation_id="inv_exec_rejected_resume",
    )
    approval = first.approval
    assert approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=ApprovalRequestStatus.REJECTED,
            request_ref=approval.request_ref,
            resolution_ref="artifact://approvals/rejected-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:00:04+00:00",
        )
    )

    resumed = engine.continue_after_approval(invocation_id="inv_exec_rejected_resume")

    assert resumed.invocation.status is EngineInvocationStatus.CANCELLED
    assert resumed.approval is not None
    assert resumed.approval.status is ApprovalRequestStatus.REJECTED
    assert (
        repositories.runs.list_by_invocation(
            session.session_id, "inv_exec_rejected_resume"
        )
        == []
    )


def test_execution_engine_status_polling_finalizes_background_run() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, BackgroundRunner())

    started = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_exec_bg",
    )
    status = engine.get_pipeline_status(
        session_id=session.session_id,
        invocation_id="inv_exec_bg",
    )

    assert started.invocation.status is EngineInvocationStatus.RUNNING
    assert status["invocation"]["status"] == "succeeded"
    assert status["artifacts"][0]["artifact_id"] == "run_inv_exec_bg:target_out"


def test_execution_engine_rejects_cross_session_status_before_runner_poll() -> None:
    repositories = _build_repositories()
    owner_session = _seed_session(repositories)
    foreign_session = Session(
        session_id="sess_foreign",
        project_id="proj_foreign",
        title="Foreign execution",
        objective="Must not access another session run",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-20T12:01:00+00:00",
        updated_at="2026-04-20T12:01:00+00:00",
    )
    repositories.sessions.save(foreign_session)

    class RecordingBackgroundRunner(BackgroundRunner):
        def __init__(self) -> None:
            self.status_calls: list[str] = []

        def get_execution_status(self, *, run_id: str):  # type: ignore[no-untyped-def]
            self.status_calls.append(run_id)
            return super().get_execution_status(run_id=run_id)

    runner = RecordingBackgroundRunner()
    engine = ExecutionEngine(repositories, runner)
    started = engine.start_execution(
        session_id=owner_session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_cross_session_status",
    )
    assert started.run is not None

    with pytest.raises(ValueError, match="belongs to session"):
        engine.get_pipeline_status(
            session_id=foreign_session.session_id,
            invocation_id="inv_cross_session_status",
        )

    assert runner.status_calls == []
    persisted = repositories.runs.get_by_invocation(
        owner_session.session_id,
        "inv_cross_session_status",
    )
    assert persisted is not None
    assert persisted.runner_run_id == started.run.runner_run_id


def test_execution_engine_compiles_staged_inputs_from_session_artifacts() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(repositories, runner)

    engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_exec_staging",
    )

    runspec = runner.payloads[0]["runspec"]
    assert runspec["inputs"][0]["artifact_id"] == "art_001"
    assert runspec["inputs"][0]["local_path"] == "/tmp/input_structure.pdb"
    assert runspec["inputs"][0]["remote_path"] == "target.pdb"
    assert runspec["expected_outputs"][0]["path"] == "target_out"
    assert "/tmp/input_structure.pdb" not in " ".join(runspec["command"])


def test_execution_engine_persists_preprocess_artifact_and_stages_it_for_vina() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        preprocess_adapter=FakeVinaPreprocessAdapter(),
    )

    result = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Dock ligand",
            "required_artifact_ids": ["art_001", "art_002"],
            "catalog_tool_id": "vina",
            "require_approval": False,
        },
        invocation_id="inv_exec_vina_preprocess",
    )

    runspec = runner.payloads[0]["runspec"]
    assert runspec["inputs"][0]["local_path"] == "/tmp/preprocess/receptor.pdbqt"
    assert runspec["inputs"][1]["local_path"] == "/tmp/ligand.pdbqt"
    preprocess_records = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.metadata and artifact.metadata.get("source") == "preprocess"
    ]
    assert [item["artifact_id"] for item in runspec["inputs"]] == [
        preprocess_records[0].artifact_id,
        "art_002",
    ]
    assert preprocess_records[0].metadata["source_artifact_id"] == "art_001"
    assert result.artifacts[0].metadata["preprocess_artifact_ids"] == [
        preprocess_records[0].artifact_id
    ]


def test_execution_engine_rejects_compiled_input_local_path_injection() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        compiler=InjectingCompiler(),
    )

    try:
        engine.start_execution(
            session_id=session.session_id,
            task_id="task_001",
            handoff={
                "execution_goal": "Run an unsafe request",
                "required_artifact_ids": ["art_001"],
                "catalog_tool_id": "fpocket",
                "require_approval": False,
            },
            invocation_id="inv_exec_injection",
        )
    except ValueError as exc:
        assert "local_path" in str(exc)
    else:
        raise AssertionError("unsafe compiled local_path was accepted")


def test_execution_engine_reconcile_closes_background_completion_without_protocol_output_writeback() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ExecutionEngine(repositories, BackgroundRunner())
    protocol = ProtocolService(repositories)

    started = engine.start_execution(
        session_id=session.session_id,
        task_id="task_001",
        handoff={
            "execution_goal": "Run fpocket on the selected structure",
            "required_artifact_ids": ["art_001"],
            "catalog_tool_id": "fpocket",
            "require_approval": False,
        },
        invocation_id="inv_exec_bg_reconcile",
    )
    assert started.invocation.output_ref is None

    protocol.complete_background_task(
        session_id=session.session_id,
        correlation_id="corr_exec_bg",
        recipient="harness",
        payload_ref="artifact://engine/inv_exec_bg_reconcile/background.json",
        invocation_id="inv_exec_bg_reconcile",
        success=True,
    )
    assert repositories.invocations.get("inv_exec_bg_reconcile").output_ref is None

    reconciled = engine.reconcile_execution(
        session_id=session.session_id,
        invocation_id="inv_exec_bg_reconcile",
    )

    assert reconciled.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert reconciled.invocation.output_ref is not None
    assert reconciled.artifacts[0].artifact_id == "run_inv_exec_bg_reconcile:target_out"


def test_execution_pipeline_rejects_legacy_handoff_input() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_legacy_handoff_rejected",
        _fpocket_pipeline_code(),
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    registry = ToolRegistry()
    register_execution_tools(registry, engine)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    master_router = registry.to_tool_router(context)
    master_step = build_agent_step_context(context, call_index=0)
    assert "execution.pipeline.start" not in {
        spec.tool_name for spec in master_router.model_visible_specs(master_step)
    }
    router, step_context = _executor_step(context)
    specs = {spec.tool_name: spec for spec in router.model_visible_specs(step_context)}
    start_governance = router.governance(step_context, "execution.pipeline.start")
    status_governance = router.governance(step_context, "execution.pipeline.status")

    assert set(engine.descriptor.tool_names) <= set(specs)
    assert specs["execution.pipeline.start"].input_schema["required"] == [
        "task_id",
        "code_artifact_id",
    ]
    assert start_governance is not None
    assert start_governance.side_effect is ToolSideEffect.APPROVAL
    assert start_governance.approval_required is True
    assert status_governance is not None
    assert status_governance.side_effect is ToolSideEffect.READ
    missing = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_missing_code",
            tool_name="execution.pipeline.start",
            arguments={"task_id": "task_001"},
            task_id="task_001",
            lane_id="lane_001",
        ),
    )
    result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_001",
            tool_name="execution.pipeline.start",
            arguments={
                "task_id": "task_001",
                "code_artifact_id": code_artifact_id,
                "inputs": {
                    "handoff": {
                        "execution_goal": "Run fpocket on the selected structure",
                        "required_artifact_ids": ["art_001"],
                        "catalog_tool_id": "fpocket",
                        "require_approval": False,
                    },
                },
            },
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    assert missing.status == "invalid_tool_arguments"
    assert result.ok is False
    assert "unsupported_pipeline_handoff" in result.content


def test_pipeline_start_requires_code_artifact_id_and_rejects_inline_code() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    missing = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        inputs={"artifact_ids": ["art_001"]},
    )
    inline = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code="print('inline is unsupported')\n",
        inputs={"artifact_ids": ["art_001"]},
    )

    assert missing.invocation.status is EngineInvocationStatus.FAILED
    assert missing.parsed_result is not None
    assert (
        missing.parsed_result.structured_findings["error"]["error_code"]
        == "missing_code_artifact_id"
    )
    assert inline.invocation.status is EngineInvocationStatus.FAILED
    assert inline.parsed_result is not None
    assert (
        inline.parsed_result.structured_findings["error"]["error_code"]
        == "unsupported_inline_pipeline_code"
    )


def test_pipeline_start_validates_code_artifact_scope_type_and_digest() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_digest_mismatch",
        "print('digest mismatch')\n",
    )
    artifact = repositories.artifacts.get(code_artifact_id)
    assert artifact is not None
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact.artifact_id,
            session_id=artifact.session_id,
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
            invocation_id=artifact.invocation_id,
            run_id=artifact.run_id,
            kind=artifact.kind,
            storage_uri=artifact.storage_uri,
            relative_path=artifact.relative_path,
            title=artifact.title,
            description=artifact.description,
            metadata={
                **dict(artifact.metadata or {}),
                "content_digest": "sha256:stale",
            },
            created_at=artifact.created_at,
        )
    )
    repositories.sessions.save(
        Session(
            session_id="sess_other",
            project_id="proj_001",
            title="Other",
            objective="Other",
            status=SessionStatus.ACTIVE,
            created_at="2026-04-20T12:00:00+00:00",
            updated_at="2026-04-20T12:00:00+00:00",
        )
    )
    _save_pipeline_source(
        repositories,
        artifact_id="code_other_session",
        session_id="sess_other",
        task_id=None,
        lane_id=None,
        code="print('other')\n",
    )
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())

    non_code = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id="art_001",
        inputs={"artifact_ids": ["art_001"]},
    )
    cross_session = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id="code_other_session",
        inputs={"artifact_ids": ["art_001"]},
    )
    digest_mismatch = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert non_code.parsed_result is not None
    assert (
        non_code.parsed_result.structured_findings["error"]["error_code"]
        == "invalid_code_artifact"
    )
    assert cross_session.parsed_result is not None
    assert (
        cross_session.parsed_result.structured_findings["error"]["error_code"]
        == "code_artifact_not_found"
    )
    assert digest_mismatch.parsed_result is not None
    assert (
        digest_mismatch.parsed_result.structured_findings["error"]["error_code"]
        == "source_code_digest_mismatch"
    )


def test_execution_pipeline_start_rejects_duplicate_task_invocation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_duplicate_pipeline_start",
        _fpocket_pipeline_code(),
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )
    registry = ToolRegistry()
    register_execution_tools(registry, engine)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    router, step_context = _executor_step(context)
    arguments = {
        "task_id": "task_001",
        "code_artifact_id": code_artifact_id,
        "inputs": {"artifact_ids": ["art_001"]},
    }

    first = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_start_first",
            tool_name="execution.pipeline.start",
            arguments=arguments,
            task_id="task_001",
            lane_id="lane_001",
        ),
    )
    second = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_start_second",
            tool_name="execution.pipeline.start",
            arguments=arguments,
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    assert first.ok is True
    assert second.ok is False
    assert second.status == "existing_execution_invocation"
    assert second.error_code == "existing_execution_invocation"
    assert "execution.pipeline.status" in second.hint


def test_execution_engine_tool_descriptors_derive_from_registered_runtimes() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(repositories, ImmediateSuccessRunner())
    engine_registry = EngineRegistry()
    engine_registry.register(engine)

    descriptors = engine_tool_descriptors(engine_registry)

    assert [descriptor.tool_name for descriptor in descriptors] == list(
        engine.descriptor.tool_names
    )
    start = next(
        descriptor
        for descriptor in descriptors
        if descriptor.tool_name == "execution.pipeline.start"
    )
    status = next(
        descriptor
        for descriptor in descriptors
        if descriptor.tool_name == "execution.pipeline.status"
    )
    assert start.input_schema["required"] == ["task_id", "code_artifact_id"]
    assert status.input_schema["required"] == ["invocation_id"]
    assert "Host-supervised execution pipeline" in start.description


def test_pipeline_dry_run_returns_plan_without_approval_or_runner_submit() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_dry_run",
        _fpocket_pipeline_code(),
    )
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories, runner, sandbox_runner=HandlerSandboxRunner()
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_dry_run",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
        dry_run=True,
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED, (
        None
        if result.parsed_result is None
        else result.parsed_result.structured_findings
    )
    assert result.approval is None
    assert runner.payloads == []
    assert result.parsed_result is not None
    plan = result.parsed_result.structured_findings["plan"]
    assert plan["plan_digest"]
    assert plan["source_code_artifact_id"] == code_artifact_id
    assert plan["source_code_digest"]
    assert plan["source_code_version"] == 1
    assert plan["sandbox_runtime_identity"] == _test_sandbox_runtime_identity()
    assert plan["hpc_operations"][0]["method"] == "structure_tools.fpocket"
    assert plan["approval_requirements"][0]["kind"] == "hpc_operation"


def test_pipeline_rejects_runtime_identity_drift_before_sandbox_or_runner() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    sandbox = DriftingIdentitySandboxRunner()
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_runtime_identity_drift",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_runtime_identity_drift",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_runtime_identity_drift",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "sandbox_runtime_identity_drift"
    assert error["stage"] == "sandbox_preflight"
    assert (
        error["details"]["expected_runtime_identity_digest"]
        != error["details"]["current_runtime_identity_digest"]
    )
    assert sandbox.calls == 0
    assert runner.payloads == []


def test_pipeline_dry_run_lists_bio_operations_and_rejects_direct_network() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    bio_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_dry_run",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'], output_dir='/workspace/output/bio/ncbi')\n"
        "bio.uniprot_fetch(accessions=['Q8XYZ1'], output_dir='/workspace/output/bio/uniprot', batch_size=50)\n"
        "bio.hmmer_search(hmm_artifact_id='art_hmm_001', database='refprot', output_dir='/workspace/output/bio/hmmer')\n",
    )
    network_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_direct_network",
        "import requests\nrequests.get('https://example.org')\n",
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=bio_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    rejected = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=network_code_artifact_id,
        inputs={},
        dry_run=True,
    )

    assert dry_run.parsed_result is not None
    plan = dry_run.parsed_result.structured_findings["plan"]
    assert [operation["method"] for operation in plan["bio_operations"]] == [
        "bio.ncbi_fetch_proteins",
        "bio.uniprot_fetch",
        "bio.hmmer_search",
    ]
    assert plan["resource_quota_estimate"]["bio_operation_count"] == 3
    assert plan["resource_quota_estimate"]["provider_requests"] == 3
    assert all(
        operation["approval_required"] is True for operation in plan["bio_operations"]
    )
    assert plan["approval_requirements"][0]["kind"] == "provider_operation"
    assert plan["expected_outputs"][0]["path"] == "<output_dir>/provider_request.json"
    uniprot_sequence_output = next(
        output
        for output in plan["expected_outputs"]
        if output["path"] == "<output_dir>/provider_parsed/sequences.fasta"
    )
    assert uniprot_sequence_output["optional"] is True
    assert rejected.invocation.status is EngineInvocationStatus.FAILED
    assert rejected.parsed_result is not None
    assert (
        rejected.parsed_result.structured_findings["error"]["error_code"]
        == "unsupported_sandbox_network_call"
    )


def test_pipeline_plan_counts_repeated_and_literal_bounded_sdk_calls() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    repeated_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_repeated_bio_calls",
        "from openzyme_pipeline import bio\n"
        "bio.uniprot_fetch(accessions=['P1'], output_dir='/workspace/output/bio/one')\n"
        "bio.uniprot_fetch(accessions=['P2'], output_dir='/workspace/output/bio/two')\n",
    )
    loop_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bounded_bio_loop",
        "from openzyme_pipeline import bio\n"
        "for index in range(3):\n"
        "    bio.ncbi_fetch_proteins(accessions=[str(index)], output_dir=f'/workspace/output/bio/{index}')\n",
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )

    repeated = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=repeated_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    bounded_loop = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=loop_code_artifact_id,
        inputs={},
        dry_run=True,
    )

    assert repeated.parsed_result is not None
    repeated_plan = repeated.parsed_result.structured_findings["plan"]
    assert repeated_plan["bio_operations"][0]["max_calls"] == 2
    assert (
        repeated_plan["bio_operations"][0]["quota_estimate"]["provider_requests"] == 2
    )
    assert repeated_plan["resource_quota_estimate"]["bio_operation_count"] == 2
    assert repeated_plan["resource_quota_estimate"]["provider_requests"] == 2
    assert bounded_loop.parsed_result is not None
    loop_plan = bounded_loop.parsed_result.structured_findings["plan"]
    assert loop_plan["bio_operations"][0]["max_calls"] == 3
    assert loop_plan["bio_operations"][0]["quota_estimate"]["provider_requests"] == 3
    assert loop_plan["operations"][0]["call_sites"] == [
        {"line": 3, "bounded": True, "multiplier": 3}
    ]


@pytest.mark.parametrize(
    "body",
    [
        (
            "accessions = ['P1', 'P2']\n"
            "for accession in accessions:\n"
            "    bio.uniprot_fetch(accessions=[accession], output_dir='/workspace/output/bio/dynamic')\n"
        ),
        (
            "def fetch():\n"
            "    return bio.uniprot_fetch(accessions=['P1'], output_dir='/workspace/output/bio/function')\n"
            "fetch()\n"
        ),
    ],
)
def test_pipeline_plan_rejects_sdk_calls_without_static_upper_bound(body: str) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        f"code_unbounded_{hashlib.sha256(body.encode('utf-8')).hexdigest()[:8]}",
        "from openzyme_pipeline import bio\n" + body,
    )
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories, runner, sandbox_runner=HandlerSandboxRunner()
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs={},
        dry_run=True,
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["error_code"] == "execution_plan_unbounded_calls"
    assert error["stage"] == "pipeline_static_policy"
    assert runner.payloads == []


def test_pipeline_runtime_cannot_exceed_approved_static_call_bound() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_runtime_call_bound",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P1'], output_dir='/workspace/output/bio/planned')\n",
    )
    runtime_operations = (
        (
            "bio.ncbi_fetch_proteins",
            {
                "accessions": ["P1"],
                "output_dir": "/workspace/output/bio/runtime-one",
            },
        ),
        (
            "bio.ncbi_fetch_proteins",
            {
                "accessions": ["P2"],
                "output_dir": "/workspace/output/bio/runtime-two",
            },
        ),
    )
    adapter = CountingBioFixtureAdapter()
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=BioSandboxRunner(runtime_operations),
        bio_adapter=adapter,
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_runtime_call_bound",
        code_artifact_id=code_artifact_id,
        inputs={},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_runtime_call_bound",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "execution_plan_quota_exceeded"
    assert error["stage"] == "execution_plan_quota"
    assert error["details"] == {
        "method": "bio.ncbi_fetch_proteins",
        "max_calls": 1,
        "consumed_calls": 1,
    }
    assert adapter.ncbi_calls == 1
    input_document = repositories.engine_documents.get(str(result.invocation.input_ref))
    assert input_document is not None
    assert input_document.payload["pipeline"]["operation_call_counts"] == {
        "bio.ncbi_fetch_proteins": 1
    }


def test_pipeline_dry_run_lists_bio_tool_operations_and_rejects_direct_cli() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    bio_tools_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_dry_run",
        "from openzyme_pipeline import hpc, bio_tools\n"
        "ws = hpc.workspace('aox_hmm')\n"
        "fasta = ws.stage_artifact('art_fasta_001', workspace_path='inputs/sequences.fasta')\n"
        "alignment = ws.stage_artifact('art_alignment', workspace_path='inputs/alignment.fasta')\n"
        "hmm = ws.stage_artifact('art_hmm', workspace_path='inputs/model.hmm')\n"
        "bio_tools.cdhit(input_fasta=fasta, placement=ws, identity=0.9, expected_outputs=[{'path': 'bio_tools/cdhit/clustered.fasta', 'kind': 'sequence'}])\n"
        "bio_tools.mafft(input_fasta=fasta, placement=ws, expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence'}])\n"
        "bio_tools.hmmbuild(alignment=alignment, placement=ws, expected_outputs=[{'path': 'bio_tools/hmmbuild/model.hmm', 'kind': 'result'}])\n"
        "bio_tools.hmmalign(hmm=hmm, fasta=fasta, placement=ws, expected_outputs=[{'path': 'bio_tools/hmmalign/aligned.fasta', 'kind': 'sequence'}])\n"
        "bio_tools.hmmer_search_cli(hmm=hmm, target_fasta=fasta, placement=ws, expected_outputs=[{'path': 'bio_tools/hmmer_search_cli/hits.csv', 'kind': 'result'}])\n",
    )
    subprocess_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_direct_subprocess",
        "import subprocess\nsubprocess.run(['mafft', 'input.fasta'])\n",
    )
    shell_code_artifact_id = _pipeline_source_id(
        repositories,
        "code_direct_shell",
        "from os import system\nsystem('mafft input.fasta')\n",
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=bio_tools_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    rejected = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=subprocess_code_artifact_id,
        inputs={},
        dry_run=True,
    )
    rejected_shell = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=shell_code_artifact_id,
        inputs={},
        dry_run=True,
    )

    assert dry_run.parsed_result is not None
    plan = dry_run.parsed_result.structured_findings["plan"]
    assert [operation["method"] for operation in plan["bio_tool_operations"]] == [
        "bio_tools.cdhit",
        "bio_tools.mafft",
        "bio_tools.hmmbuild",
        "bio_tools.hmmalign",
        "bio_tools.hmmer_search_cli",
    ]
    assert plan["resource_quota_estimate"]["bio_tool_operation_count"] == 5
    hmmer_cli_operation = plan["bio_tool_operations"][-1]
    assert (
        hmmer_cli_operation["route_policy_id"]
        == "bio_tools.hmmer_search_cli.disabled:v1"
    )
    assert hmmer_cli_operation["selected_backend"] == "disabled"
    assert hmmer_cli_operation["route_status"] == "disabled"
    assert hmmer_cli_operation["expected_outputs"] == []
    assert hmmer_cli_operation["quota_estimate"]["local_tool_invocations"] == 0
    assert plan["expected_outputs"][0]["path"] == "bio_tools/cdhit/clustered.fasta"
    assert rejected.invocation.status is EngineInvocationStatus.FAILED
    assert rejected.parsed_result is not None
    assert (
        rejected.parsed_result.structured_findings["error"]["error_code"]
        == "unsupported_sandbox_process_call"
    )
    assert rejected_shell.invocation.status is EngineInvocationStatus.FAILED
    assert rejected_shell.parsed_result is not None
    assert (
        rejected_shell.parsed_result.structured_findings["error"]["error_code"]
        == "unsupported_sandbox_process_call"
    )


def test_bio_tool_rejects_outputs_impossible_for_fixed_runner_before_dispatch() -> (
    None
):
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(
        repositories,
        "art_impossible_mafft_output",
    )
    workspace = _workspace_payload("impossible_mafft_output")
    staged_fasta = _stage_payload(
        repositories,
        fasta_artifact_id,
        workspace,
        "inputs/sequences.fasta",
    )
    impossible_output = {
        "path": "work/mafft/ncbi_alignment.fasta",
        "kind": "sequence",
        "format": "fasta",
    }
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_impossible_mafft_output",
        "from openzyme_pipeline import bio_tools, hpc\n"
        "ws = hpc.workspace('probe')\n"
        f"fasta = ws.stage_artifact('{fasta_artifact_id}', workspace_path='inputs/sequences.fasta')\n"
        "bio_tools.mafft(input_fasta=fasta, placement=ws, "
        f"expected_outputs={[impossible_output]!r})\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.mafft",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": [impossible_output],
                    "params": {},
                },
            ),
        )
    )
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_runner=sandbox,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_impossible_mafft_output",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_impossible_mafft_output",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "bio_tool_output_contract_mismatch"
    assert error["stage"] == "hpc_output_validation"
    assert error["retryable"] is False
    assert error["details"] == {
        "declared_paths": ["work/mafft/ncbi_alignment.fasta"],
        "expected_paths": ["bio_tools/mafft/alignment.fasta"],
    }
    assert "bio_tools/mafft/alignment.fasta" in error["hint"]
    assert runner.payloads == []


@pytest.mark.parametrize(
    ("method", "declared_paths", "expected_paths"),
    (
        (
            "bio_tools.cdhit",
            ["bio_tools/cdhit/clustered.fasta"],
            [
                "bio_tools/cdhit/clustered.fasta",
                "bio_tools/cdhit/clusters.csv",
            ],
        ),
        (
            "bio_tools.mafft",
            [
                "bio_tools/mafft/alignment.fasta",
                "bio_tools/mafft/extra.fasta",
            ],
            ["bio_tools/mafft/alignment.fasta"],
        ),
        (
            "bio_tools.hmmbuild",
            [
                "bio_tools/hmmbuild/model.hmm",
                "bio_tools/hmmbuild/model.hmm",
            ],
            ["bio_tools/hmmbuild/model.hmm"],
        ),
    ),
    ids=("missing", "extra", "duplicate"),
)
def test_bio_tool_fixed_output_contract_rejects_noncanonical_path_sets(
    method: str,
    declared_paths: list[str],
    expected_paths: list[str],
) -> None:
    engine = ExecutionEngine(_build_repositories(), CapturingSuccessRunner())

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._require_canonical_bio_tool_outputs(
            method,
            [{"path": path} for path in declared_paths],
        )

    failure = exc_info.value
    assert failure.error_type == "bio_tool_output_contract_mismatch"
    assert failure.stage == "hpc_output_validation"
    assert failure.details == {
        "declared_paths": sorted(declared_paths),
        "expected_paths": sorted(expected_paths),
    }


def test_bio_tool_fixed_output_contract_rejects_explicit_invalid_kind_before_dispatch() -> (
    None
):
    engine = ExecutionEngine(_build_repositories(), CapturingSuccessRunner())

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._require_canonical_bio_tool_outputs(
            "bio_tools.hmmbuild",
            [
                {
                    "path": "bio_tools/hmmbuild/model.hmm",
                    "kind": "model",
                    "format": "hmm",
                }
            ],
        )

    failure = exc_info.value
    assert failure.error_type == "artifact_kind_invalid"
    assert failure.stage == "hpc_output_validation"
    assert failure.retryable is False
    assert failure.sdk_method == "bio_tools.hmmbuild"
    assert failure.details == {
        "allowed_values": [
            "code",
            "log",
            "sequence",
            "structure",
            "report",
            "research_dossier",
            "result",
            "cache",
            "other",
        ],
        "declared_kind": "model",
        "path": "bio_tools/hmmbuild/model.hmm",
    }


def test_bio_tool_fixed_output_contract_rejects_directory_shape_sentinel() -> None:
    engine = ExecutionEngine(_build_repositories(), CapturingSuccessRunner())

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._require_canonical_bio_tool_outputs(
            "bio_tools.hmmbuild",
            [
                {
                    "path": "bio_tools/hmmbuild/model.hmm",
                    "kind": "directory",
                    "format": "hmm",
                }
            ],
        )

    failure = exc_info.value
    assert failure.error_type == "bio_tool_output_contract_mismatch"
    assert failure.stage == "hpc_output_validation"
    assert failure.details == {
        "mismatches": [
            {
                "field": "kind",
                "path": "bio_tools/hmmbuild/model.hmm",
                "declared": "directory",
                "expected": "result",
            }
        ]
    }


def test_bio_tool_fixed_output_contract_materializes_inferred_kind_and_format() -> None:
    engine = ExecutionEngine(_build_repositories(), CapturingSuccessRunner())

    normalized = engine._require_canonical_bio_tool_outputs(
        "bio_tools.hmmbuild",
        [{"path": "bio_tools/hmmbuild/model.hmm"}],
    )

    assert normalized == [
        {
            "path": "bio_tools/hmmbuild/model.hmm",
            "kind": "result",
            "format": "hmm",
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (("kind", "sequence", "result"), ("format", "json", "hmm")),
)
def test_bio_tool_fixed_output_contract_rejects_explicit_kind_format_drift(
    field: str,
    value: str,
    expected: str,
) -> None:
    engine = ExecutionEngine(_build_repositories(), CapturingSuccessRunner())
    declared = {
        "path": "bio_tools/hmmbuild/model.hmm",
        "kind": "result",
        "format": "hmm",
    }
    declared[field] = value

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._require_canonical_bio_tool_outputs(
            "bio_tools.hmmbuild",
            [declared],
        )

    failure = exc_info.value
    assert failure.error_type == "bio_tool_output_contract_mismatch"
    assert failure.stage == "hpc_output_validation"
    assert failure.details == {
        "mismatches": [
            {
                "field": field,
                "path": "bio_tools/hmmbuild/model.hmm",
                "declared": value,
                "expected": expected,
            }
        ]
    }


def test_pipeline_execute_after_dry_run_uses_distinct_idempotency_and_links_approval() -> (
    None
):
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_runner=HandlerSandboxRunner(),
    )
    code = _fpocket_pipeline_code()
    code_artifact_id = _pipeline_source_id(
        repositories, "code_execute_after_dry_run", code
    )
    inputs = {"artifact_ids": ["art_001"]}

    dry_run = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs=inputs,
        dry_run=True,
    )
    execute = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs=inputs,
        dry_run=False,
    )

    assert dry_run.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert execute.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert execute.approval is not None
    assert execute.invocation.approval_id == execute.approval.approval_id
    assert execute.parsed_result is not None
    assert (
        execute.parsed_result.structured_findings["plan"]["source_code_artifact_id"]
        == code_artifact_id
    )
    assert dry_run.invocation.idempotency_key != execute.invocation.idempotency_key
    approvals = repositories.approvals.list_by_session("sess_001")
    assert [approval.approval_id for approval in approvals] == [
        execute.approval.approval_id
    ]


def test_pipeline_single_plan_approval_policy_gates_bio_tool_execution() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_single_plan_bio_tools",
        "from openzyme_pipeline import bio, bio_tools\n"
        "refs = bio.ncbi_fetch_proteins(accessions=['AAC72747.1'], output_dir='/workspace/output/bio/ncbi')\n"
        "from openzyme_pipeline import hpc\n"
        "ws = hpc.workspace('aox_hmm')\n"
        "remote_refs = ws.stage_artifact(refs['artifact_ids'][0], workspace_path='inputs/reference.fasta')\n"
        "bio_tools.cdhit(input_fasta=remote_refs, placement=ws, identity=0.9, expected_outputs=[{'path': 'bio_tools/cdhit/clustered.fasta', 'kind': 'sequence'}])\n",
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=BioSandboxRunner(()),
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs={"approval_policy": "single_plan"},
    )

    assert result.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert result.approval is not None
    assert result.approval.kind == "execution_pipeline_plan"
    assert result.parsed_result is not None
    plan = result.parsed_result.structured_findings["plan"]
    assert plan["approval_requirements"][0]["kind"] == "pipeline_plan"
    assert plan["bio_operations"][0]["approval_required"] is True
    assert plan["bio_tool_operations"][0]["approval_required"] is True


def test_pipeline_bio_ncbi_and_uniprot_fetch_persist_bounded_artifacts() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_fetch",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'], output_dir='/workspace/output/bio/ncbi')\n"
        "bio.uniprot_fetch(accessions=['Q8XYZ1', 'MISSING999'], output_dir='/workspace/output/bio/uniprot', batch_size=1)\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.ncbi_fetch_proteins",
                {
                    "accessions": ["P12345"],
                    "fields": ["taxonomy"],
                    "output_dir": "/workspace/output/bio/ncbi",
                },
            ),
            (
                "bio.uniprot_fetch",
                {
                    "accessions": ["Q8XYZ1", "MISSING999"],
                    "fields": ["length", "taxonomy", "reviewed"],
                    "batch_size": 1,
                    "output_dir": "/workspace/output/bio/uniprot",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_fetch",
        code_artifact_id=code_artifact_id,
        inputs={"approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_fetch", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert len(sandbox.results) == 2
    assert sandbox.results[0]["artifact_count"] == 4
    assert (
        sandbox.results[1]["warnings"][0]["warning_code"] == "partial_accession_missing"
    )
    assert "sequence" not in sandbox.results[0]["artifacts"][0]["metadata"]
    artifacts = repositories.artifacts.list_by_invocation(
        "sess_001", "inv_pipeline_bio_fetch"
    )
    bio_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.metadata
        and artifact.metadata.get("producer") == "host_supervised_bio_provider"
    ]
    assert {artifact.relative_path for artifact in bio_artifacts} == {
        "bio/ncbi/provider_request.json",
        "bio/ncbi/provider_observation.json",
        "bio/ncbi/provider_parsed/proteins.fasta",
        "bio/ncbi/provider_parsed/proteins.metadata.json",
        "bio/uniprot/provider_request.json",
        "bio/uniprot/provider_observation.json",
        "bio/uniprot/provider_parsed/sequences.fasta",
        "bio/uniprot/provider_parsed/metadata.json",
    }
    fasta_artifact = next(
        artifact
        for artifact in bio_artifacts
        if artifact.relative_path == "bio/ncbi/provider_parsed/proteins.fasta"
    )
    assert fasta_artifact.kind is ArtifactKind.SEQUENCE
    assert fasta_artifact.metadata is not None
    assert fasta_artifact.metadata["provider"] == "ncbi"
    assert fasta_artifact.metadata["response_digest"].startswith("sha256:")
    assert fasta_artifact.metadata["source_code_artifact_id"] == code_artifact_id
    assert fasta_artifact.metadata["content_digest"] == _content_digest(
        Path(fasta_artifact.storage_uri).read_text(encoding="utf-8")
    )
    assert (
        Path(fasta_artifact.storage_uri)
        .read_text(encoding="utf-8")
        .startswith(">P12345")
    )
    metadata_artifact = next(
        artifact
        for artifact in bio_artifacts
        if artifact.relative_path == "bio/uniprot/provider_parsed/metadata.json"
    )
    metadata_payload = json.loads(
        Path(metadata_artifact.storage_uri).read_text(encoding="utf-8")
    )
    assert "sequence" not in metadata_payload["records"][0]
    status = engine.get_pipeline_status(
        session_id="sess_001",
        invocation_id="inv_pipeline_bio_fetch",
    )
    assert status["details"]["bio_artifact_ids"]
    assert "P12345" not in str(status.get("sandbox_outcome", {}))


def _compat_uniprot_call_context(
    batch_size: object,
) -> tuple[
    ExecutionEngine,
    Session,
    EngineInvocation,
    dict[str, object],
    RecordingUniprotFixtureAdapter,
]:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_compat_uniprot_batch",
        "from openzyme_pipeline import bio\n"
        "bio.uniprot_fetch(accessions=['P12345'], output_dir='/workspace/output/bio/compat-batch', batch_size=1)\n",
    )
    adapter = RecordingUniprotFixtureAdapter()
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(),
        bio_adapter=adapter,
        allow_bio_fixture_adapter=True,
    )
    started = engine.start_pipeline(
        session_id=session.session_id,
        task_id="task_001",
        invocation_id="inv_compat_uniprot_batch",
        code_artifact_id=code_artifact_id,
        inputs={},
        dry_run=True,
    )
    assert started.invocation.status is EngineInvocationStatus.SUCCEEDED
    params: dict[str, object] = {
        "accessions": ["P12345"],
        "fields": [],
        "batch_size": batch_size,
        "output_dir": "/workspace/output/bio/compat-batch",
    }
    operation_key = engine._pipeline_operation_key("bio.uniprot_fetch", params)
    engine._update_pipeline_document(
        started.invocation,
        {"approved_operation_keys": [operation_key]},
    )
    return engine, session, started.invocation, params, adapter


def _controlled_uniprot_call_context(
    *,
    tmp_path: Path,
    batch_size: object,
) -> tuple[
    ExecutionEngine,
    ControlledOperation,
    dict[str, object],
    RecordingUniprotFixtureAdapter,
]:
    repositories = _build_repositories()
    _seed_session(repositories)
    workspace_root = tmp_path / "workspaces"
    sandbox_workspace_id = _seed_sandbox_adapter_workspace(
        repositories,
        workspace_root=workspace_root,
    )
    params: dict[str, object] = {
        "accessions": ["P12345"],
        "fields": [],
        "batch_size": batch_size,
        "output_dir": "/workspace/output/bio/controlled-batch",
    }
    operation = _sandbox_uniprot_operation(
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id="srun_controlled_uniprot_batch",
        params=params,
        operation_id="op_controlled_uniprot_batch",
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    adapter = RecordingUniprotFixtureAdapter()
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        bio_adapter=adapter,
        allow_bio_fixture_adapter=True,
        sandbox_workspace_root=workspace_root,
    )
    return engine, operation, params, adapter


@pytest.mark.parametrize("batch_size", (True, 1.5, "1"))
def test_compat_uniprot_batch_size_rejects_values_int_would_coerce(
    batch_size: object,
) -> None:
    engine, session, invocation, params, adapter = _compat_uniprot_call_context(
        batch_size
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._run_pipeline_bio(
            session=session,
            invocation=invocation,
            method="bio.uniprot_fetch",
            params=params,
        )

    assert exc_info.value.error_type == "invalid_batch_size"
    assert exc_info.value.stage == "bio_input_validation"
    assert exc_info.value.retryable is False
    assert exc_info.value.details == {"batch_size": batch_size}
    assert adapter.batch_sizes == []


def test_compat_uniprot_batch_size_accepts_exact_integer() -> None:
    engine, session, invocation, params, adapter = _compat_uniprot_call_context(1)

    result = engine._run_pipeline_bio(
        session=session,
        invocation=invocation,
        method="bio.uniprot_fetch",
        params=params,
    )

    assert result["artifact_count"] == 4
    assert adapter.batch_sizes == [1]
    assert type(adapter.batch_sizes[0]) is int


@pytest.mark.parametrize("batch_size", (True, 1.5, "1"))
def test_controlled_uniprot_batch_size_rejects_values_int_would_coerce(
    tmp_path: Path,
    batch_size: object,
) -> None:
    engine, operation, params, adapter = _controlled_uniprot_call_context(
        tmp_path=tmp_path,
        batch_size=batch_size,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine.execute_sandbox_adapter_operation(
            operation,
            {"adapter_params": params},
        )

    assert exc_info.value.error_type == "provider_invalid_request"
    assert exc_info.value.stage == "bio_input_validation"
    assert exc_info.value.retryable is False
    assert exc_info.value.details["batch_size"] == batch_size
    assert adapter.batch_sizes == []


def test_controlled_uniprot_batch_size_accepts_exact_integer(tmp_path: Path) -> None:
    engine, operation, params, adapter = _controlled_uniprot_call_context(
        tmp_path=tmp_path,
        batch_size=1,
    )

    result = engine.execute_sandbox_adapter_operation(
        operation,
        {"adapter_params": params},
    )

    assert len(result["adapter_result"]["registered_artifact_ids"]) == 4
    assert adapter.batch_sizes == [1]
    assert type(adapter.batch_sizes[0]) is int


def _seed_bio_later_draft_conflict(
    *,
    repositories: CoreRepositories,
    output_root: Path,
    output_dir_relative: str,
    suffix: str,
) -> tuple[
    tuple[BioArtifactDraft, BioArtifactDraft],
    Path,
    Path,
    str,
    str,
]:
    first_sentinel = '{"sentinel":"first"}\n'
    later_sentinel = '{"sentinel":"later"}\n'
    first_path = output_root / "first.json"
    later_path = output_root / "later.json"
    first_path.parent.mkdir(parents=True, exist_ok=True)
    first_path.write_text(first_sentinel, encoding="utf-8")
    later_path.write_text(later_sentinel, encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=f"art_existing_bio_later_{suffix}",
            session_id="sess_001",
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="seed_invocation",
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri=str(later_path),
            relative_path=f"{output_dir_relative}/later.json",
            title="later.json",
            description=None,
            metadata={
                "format": "json",
                "content_digest": _content_digest(later_sentinel),
            },
            created_at="2026-07-20T00:00:00+00:00",
        )
    )
    drafts = (
        BioArtifactDraft(
            relative_path="first.json",
            kind=ArtifactKind.RESULT,
            title="first.json",
            content='{"replacement":"first"}\n',
            format="json",
            metadata={},
        ),
        BioArtifactDraft(
            relative_path="later.json",
            kind=ArtifactKind.RESULT,
            title="later.json",
            content='{"replacement":"later"}\n',
            format="json",
            metadata={},
        ),
    )
    return drafts, first_path, later_path, first_sentinel, later_sentinel


def _assert_later_bio_conflict_left_no_partial_write(
    *,
    repositories: CoreRepositories,
    output_dir_relative: str,
    first_path: Path,
    later_path: Path,
    first_sentinel: str,
    later_sentinel: str,
) -> None:
    assert first_path.read_text(encoding="utf-8") == first_sentinel
    assert later_path.read_text(encoding="utf-8") == later_sentinel
    assert not any(
        artifact.relative_path == f"{output_dir_relative}/first.json"
        for artifact in repositories.artifacts.list_by_session("sess_001")
    )


def test_compat_bio_artifact_persistence_preflights_later_conflict_before_writes(
    tmp_path: Path,
) -> None:
    del tmp_path
    engine, session, invocation, _params, _adapter = _compat_uniprot_call_context(1)
    engine._ensure_pipeline_artifact_boundary_workspace(invocation)
    workspace_root = engine.sandbox_workspace_root
    assert workspace_root is not None
    output_dir_relative = "bio/compat-preflight"
    output_root = (
        workspace_root
        / engine._pipeline_sandbox_workspace_id(invocation)
        / "output"
        / output_dir_relative
    )
    drafts, first_path, later_path, first_sentinel, later_sentinel = (
        _seed_bio_later_draft_conflict(
            repositories=engine.repositories,
            output_root=output_root,
            output_dir_relative=output_dir_relative,
            suffix="compat",
        )
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._persist_bio_artifacts(
            session=session,
            invocation=invocation,
            output_dir_relative=output_dir_relative,
            operation_key="compat-preflight",
            drafts=drafts,
            request_metadata={
                "sdk_method": "bio.uniprot_fetch",
                "provider": "uniprot",
                "output_dir": f"/workspace/output/{output_dir_relative}",
            },
        )

    assert exc_info.value.error_type == "provider_output_path_invalid"
    assert exc_info.value.details["relative_path"].endswith("/later.json")
    _assert_later_bio_conflict_left_no_partial_write(
        repositories=engine.repositories,
        output_dir_relative=output_dir_relative,
        first_path=first_path,
        later_path=later_path,
        first_sentinel=first_sentinel,
        later_sentinel=later_sentinel,
    )


def test_controlled_bio_artifact_persistence_preflights_later_conflict_before_writes(
    tmp_path: Path,
) -> None:
    engine, operation, _params, _adapter = _controlled_uniprot_call_context(
        tmp_path=tmp_path,
        batch_size=1,
    )
    output_dir_relative = "bio/controlled-preflight"
    workspace_root = engine.sandbox_workspace_root
    assert workspace_root is not None
    output_root = (
        workspace_root
        / operation.sandbox_workspace_id
        / "output"
        / output_dir_relative
    )
    drafts, first_path, later_path, first_sentinel, later_sentinel = (
        _seed_bio_later_draft_conflict(
            repositories=engine.repositories,
            output_root=output_root,
            output_dir_relative=output_dir_relative,
            suffix="controlled",
        )
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._persist_sandbox_bio_artifacts(
            operation=operation,
            output_dir_relative=output_dir_relative,
            operation_key=operation.operation_id,
            drafts=drafts,
            request_metadata={
                "sdk_method": "bio.uniprot_fetch",
                "provider": "uniprot",
                "output_dir": f"/workspace/output/{output_dir_relative}",
            },
        )

    assert exc_info.value.error_type == "provider_output_path_invalid"
    assert exc_info.value.details["relative_path"].endswith("/later.json")
    _assert_later_bio_conflict_left_no_partial_write(
        repositories=engine.repositories,
        output_dir_relative=output_dir_relative,
        first_path=first_path,
        later_path=later_path,
        first_sentinel=first_sentinel,
        later_sentinel=later_sentinel,
    )


def _oversized_later_bio_metadata_drafts() -> tuple[
    BioArtifactDraft,
    BioArtifactDraft,
]:
    return (
        BioArtifactDraft(
            relative_path="first.json",
            kind=ArtifactKind.RESULT,
            title="first.json",
            content='{"first":true}\n',
            format="json",
            metadata={},
        ),
        BioArtifactDraft(
            relative_path="later.json",
            kind=ArtifactKind.RESULT,
            title="later.json",
            content='{"later":true}\n',
            format="json",
            metadata={"oversized": "x" * 300_000},
        ),
    )


def _assert_oversized_bio_metadata_left_no_partial_effect(
    *,
    repositories: CoreRepositories,
    output_root: Path,
    output_dir_relative: str,
) -> None:
    assert not (output_root / "first.json").exists()
    assert not (output_root / "later.json").exists()
    assert not any(
        artifact.relative_path.startswith(f"{output_dir_relative}/")
        for artifact in repositories.artifacts.list_by_session("sess_001")
    )


def test_compat_bio_artifact_persistence_preflights_all_metadata_before_writes() -> None:
    engine, session, invocation, _params, _adapter = _compat_uniprot_call_context(1)
    engine._ensure_pipeline_artifact_boundary_workspace(invocation)
    workspace_root = engine.sandbox_workspace_root
    assert workspace_root is not None
    output_dir_relative = "bio/compat-metadata-preflight"
    output_root = (
        workspace_root
        / engine._pipeline_sandbox_workspace_id(invocation)
        / "output"
        / output_dir_relative
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._persist_bio_artifacts(
            session=session,
            invocation=invocation,
            output_dir_relative=output_dir_relative,
            operation_key="compat-metadata-preflight",
            drafts=_oversized_later_bio_metadata_drafts(),
            request_metadata={
                "sdk_method": "bio.uniprot_fetch",
                "provider": "uniprot",
                "output_dir": f"/workspace/output/{output_dir_relative}",
            },
        )

    assert exc_info.value.error_type == "provider_artifactization_failed"
    assert exc_info.value.details["boundary_error_code"] == (
        "artifact_registration_metadata_inline_too_large"
    )
    _assert_oversized_bio_metadata_left_no_partial_effect(
        repositories=engine.repositories,
        output_root=output_root,
        output_dir_relative=output_dir_relative,
    )


def test_controlled_bio_artifact_persistence_preflights_all_metadata_before_writes(
    tmp_path: Path,
) -> None:
    engine, operation, _params, _adapter = _controlled_uniprot_call_context(
        tmp_path=tmp_path,
        batch_size=1,
    )
    workspace_root = engine.sandbox_workspace_root
    assert workspace_root is not None
    output_dir_relative = "bio/controlled-metadata-preflight"
    output_root = (
        workspace_root
        / operation.sandbox_workspace_id
        / "output"
        / output_dir_relative
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine._persist_sandbox_bio_artifacts(
            operation=operation,
            output_dir_relative=output_dir_relative,
            operation_key=operation.operation_id,
            drafts=_oversized_later_bio_metadata_drafts(),
            request_metadata={
                "sdk_method": "bio.uniprot_fetch",
                "provider": "uniprot",
                "output_dir": f"/workspace/output/{output_dir_relative}",
            },
        )

    assert exc_info.value.error_type == "provider_artifactization_failed"
    assert exc_info.value.details["boundary_error_code"] == (
        "artifact_registration_metadata_inline_too_large"
    )
    _assert_oversized_bio_metadata_left_no_partial_effect(
        repositories=engine.repositories,
        output_root=output_root,
        output_dir_relative=output_dir_relative,
    )


def test_sandbox_adapter_executor_runs_bio_provider_and_registers_artifacts(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = AgentMember(
        agent_id="agent:executor",
        session_id=session.session_id,
        lane_id="lane_001",
        task_id="task_001",
        name="executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
        member_id="member_executor",
    )
    repositories.agents.save(agent)
    workspace_root = tmp_path / "workspaces"
    workspace = SandboxWorkspaceService(
        repositories, workspace_root=workspace_root
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id="member_executor",
        focus_task_id="task_001",
        focus_lane_id="lane_001",
    )
    source_path = (
        workspace_root / workspace.sandbox_workspace_id / "src" / "pipeline.py"
    )
    source_path.write_text("from openzyme_pipeline import bio\n", encoding="utf-8")
    boundary = ArtifactBoundaryService(
        repositories, workspace_root=workspace_root
    )
    snapshot = boundary.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths=["pipeline.py"],
        entrypoint="pipeline.py",
        metadata={"producer": "test"},
    )
    params = {
        "accessions": ["AAB57849.1"],
        "fields": ["definition"],
        "output_dir": "/workspace/output/bio/ncbi",
    }
    operation = ControlledOperation(
        operation_id="op_sandbox_provider",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id="srun_sandbox_provider",
        logical_operation_key="bio.ncbi_fetch_proteins",
        operation_digest="sha256:operation",
        params_digest=_payload_digest(params),
        backend_category="provider_http",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-05-31T00:00:01+00:00",
        updated_at="2026-05-31T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_id="appr_sandbox_provider",
        approval_state="approved",
        route_reason="static_policy:v1",
        source_snapshot_artifact_id=snapshot.artifact.artifact_id,
        source_snapshot_digest=snapshot.source_tree_digest,
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio",
        function_name="ncbi_fetch_proteins",
        route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
        placement="provider",
        selected_backend="provider_http",
        resource_class="network_io",
        runtime_packaging_id="provider_http:v1",
        provider_config_digest="provider_config:ncbi:v1",
        expected_outputs_summary={"output_dir": "/workspace/output/bio/ncbi"},
        resource_estimate={"network_io": True},
        idempotency_key="bio.ncbi_fetch_proteins:" + _payload_digest(params),
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    source_path.write_text(
        "from openzyme_pipeline import bio\n# later unrelated snapshot\n",
        encoding="utf-8",
    )
    later_snapshot = boundary.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths=["pipeline.py"],
        entrypoint="pipeline.py",
        metadata={"producer": "test-later"},
    )
    assert later_snapshot.artifact.artifact_id != operation.source_snapshot_artifact_id
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
        sandbox_workspace_root=workspace_root,
    )

    result = engine.execute_sandbox_adapter_operation(
        operation, {"adapter_params": params}
    )

    adapter_result = result["adapter_result"]
    assert adapter_result["provider_request_id"].startswith("provider_req_")
    assert adapter_result["bounded_summary"]["record_count"] == 1
    artifact_ids = adapter_result["registered_artifact_ids"]
    assert len(artifact_ids) == 4
    artifacts = [
        repositories.artifacts.get(artifact_id) for artifact_id in artifact_ids
    ]
    assert all(artifact is not None for artifact in artifacts)
    relative_paths = {
        artifact.relative_path for artifact in artifacts if artifact is not None
    }
    assert relative_paths == {
        "bio/ncbi/provider_request.json",
        "bio/ncbi/provider_observation.json",
        "bio/ncbi/provider_parsed/proteins.fasta",
        "bio/ncbi/provider_parsed/proteins.metadata.json",
    }
    fasta_artifact = next(
        artifact
        for artifact in artifacts
        if artifact is not None
        and artifact.relative_path == "bio/ncbi/provider_parsed/proteins.fasta"
    )
    assert fasta_artifact.metadata is not None
    assert fasta_artifact.metadata["controlled_operation_id"] == operation.operation_id
    assert (
        fasta_artifact.metadata["source_code_artifact_id"]
        == snapshot.artifact.artifact_id
    )
    assert (
        fasta_artifact.metadata["source_snapshot_artifact_id"]
        == operation.source_snapshot_artifact_id
    )
    assert (
        fasta_artifact.metadata["source_tree_digest"]
        == operation.source_snapshot_digest
    )
    assert (
        dict(fasta_artifact.metadata["provenance"])[
            "source_snapshot_artifact_id"
        ]
        == operation.source_snapshot_artifact_id
    )
    assert (
        Path(fasta_artifact.storage_uri)
        .read_text(encoding="utf-8")
        .startswith(">AAB57849.1")
    )


def test_sandbox_bio_provider_failure_persists_diagnostic_transcript(
    tmp_path: Path,
) -> None:
    class FailingBioAdapter:
        def ncbi_fetch_proteins(self, **_kwargs: object) -> BioSdkResult:
            raise PipelineSdkFailure(
                error_type="bio_provider_timeout",
                message="provider timed out",
                hint="retry after recovery",
                stage="bio_provider_request",
                retryable=True,
                sdk_method="bio.ncbi_fetch_proteins",
                details={"provider": "ncbi", "safe_batch_index": 2},
            )

    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.agents.save(
        AgentMember(
            agent_id="agent:executor",
            session_id=session.session_id,
            lane_id="lane_001",
            task_id="task_001",
            name="executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-05-31T00:00:00+00:00",
            updated_at="2026-05-31T00:00:00+00:00",
            member_id="member_executor",
        )
    )
    workspace_root = tmp_path / "workspaces"
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=workspace_root,
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id="member_executor",
        focus_task_id="task_001",
        focus_lane_id="lane_001",
    )
    source_path = (
        workspace_root / workspace.sandbox_workspace_id / "src" / "pipeline.py"
    )
    source_path.write_text("from openzyme_pipeline import bio\n", encoding="utf-8")
    snapshot = ArtifactBoundaryService(
        repositories,
        workspace_root=workspace_root,
    ).snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths=["pipeline.py"],
        entrypoint="pipeline.py",
        metadata={"producer": "test"},
    )
    params = {
        "accessions": ["AAB57849.1"],
        "fields": ["definition"],
        "output_dir": "/workspace/output/bio/ncbi-failure",
    }
    operation = ControlledOperation(
        operation_id="op_sandbox_provider_failure",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id="srun_sandbox_provider_failure",
        logical_operation_key="bio.ncbi_fetch_proteins",
        operation_digest="sha256:operation-failure",
        params_digest=_payload_digest(params),
        backend_category="provider_http",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-05-31T00:00:01+00:00",
        updated_at="2026-05-31T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_id="appr_sandbox_provider_failure",
        approval_state="approved",
        route_reason="static_policy:v1",
        source_snapshot_artifact_id=snapshot.artifact.artifact_id,
        source_snapshot_digest=snapshot.source_tree_digest,
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio",
        function_name="ncbi_fetch_proteins",
        route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
        placement="provider",
        selected_backend="provider_http",
        resource_class="network_io",
        runtime_packaging_id="provider_http:v1",
        provider_config_digest="provider_config:ncbi:v1",
        expected_outputs_summary={
            "output_dir": "/workspace/output/bio/ncbi-failure"
        },
        resource_estimate={"network_io": True},
        idempotency_key="bio.ncbi_fetch_proteins:" + _payload_digest(params),
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        bio_adapter=FailingBioAdapter(),  # type: ignore[arg-type]
        sandbox_workspace_root=workspace_root,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine.execute_sandbox_adapter_operation(
            operation,
            {"adapter_params": params},
        )

    failure = exc_info.value
    assert failure.error_type == "provider_timeout"
    assert failure.stage == "provider_request"
    assert failure.retryable is True
    assert failure.details["provider"] == "ncbi"
    assert failure.details["safe_batch_index"] == 2
    assert len(failure.details["diagnostic_artifact_ids"]) == 3
    assert failure.details["details_ref"].endswith("/provider_error.json")
    diagnostic_artifacts = [
        repositories.artifacts.get(artifact_id)
        for artifact_id in failure.details["diagnostic_artifact_ids"]
    ]
    assert all(artifact is not None for artifact in diagnostic_artifacts)
    assert {
        artifact.relative_path
        for artifact in diagnostic_artifacts
        if artifact is not None
    } == {
        "bio/ncbi-failure/provider_request.json",
        "bio/ncbi-failure/provider_observation.json",
        "bio/ncbi-failure/provider_error.json",
    }
    error_artifact = next(
        artifact
        for artifact in diagnostic_artifacts
        if artifact is not None
        and artifact.relative_path.endswith("provider_error.json")
    )
    error_payload = json.loads(
        Path(error_artifact.storage_uri).read_text(encoding="utf-8")
    )
    assert error_payload["code"] == "provider_timeout"
    assert error_payload["stage"] == "provider_request"
    assert error_payload["details"] == {
        "provider": "ncbi",
        "safe_batch_index": 2,
    }


def test_sandbox_adapter_executor_downloads_rcsb_structure_as_sealed_manifest(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = AgentMember(
        agent_id="agent:executor",
        session_id=session.session_id,
        lane_id="lane_001",
        task_id="task_001",
        name="executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
        member_id="member_executor",
    )
    repositories.agents.save(agent)
    workspace_root = tmp_path / "workspaces"
    workspace = SandboxWorkspaceService(
        repositories, workspace_root=workspace_root
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id="member_executor",
        focus_task_id="task_001",
        focus_lane_id="lane_001",
    )
    source_path = (
        workspace_root / workspace.sandbox_workspace_id / "src" / "pipeline.py"
    )
    source_path.write_text("from openzyme_pipeline import rcsb_pdb\n", encoding="utf-8")
    snapshot = ArtifactBoundaryService(
        repositories, workspace_root=workspace_root
    ).snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths=["pipeline.py"],
        entrypoint="pipeline.py",
        metadata={"producer": "test"},
    )
    params = {
        "pdb_id": "6LEH",
        "format": "pdb",
        "output_dir": "/workspace/output/rcsb_pdb/6leh",
    }
    operation = ControlledOperation(
        operation_id="op_sandbox_rcsb_provider",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id="srun_sandbox_rcsb_provider",
        logical_operation_key="rcsb_pdb.download_structure",
        operation_digest="sha256:operation-rcsb",
        params_digest=_payload_digest(params),
        backend_category="provider_http",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-05-31T00:00:01+00:00",
        updated_at="2026-05-31T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_id="appr_sandbox_rcsb_provider",
        approval_state="approved",
        route_reason="static_policy:v1",
        source_snapshot_artifact_id=snapshot.artifact.artifact_id,
        source_snapshot_digest=snapshot.source_tree_digest,
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="rcsb_pdb",
        function_name="download_structure",
        route_policy_id="rcsb_pdb.download_structure.provider:v1",
        placement="provider",
        selected_backend="provider_http",
        resource_class="network_io",
        runtime_packaging_id="provider_http:v1",
        provider_config_digest="provider_config:rcsb_pdb:v1",
        expected_outputs_summary={"output_dir": "/workspace/output/rcsb_pdb/6leh"},
        resource_estimate={"network_io": True},
        idempotency_key="rcsb_pdb.download_structure:" + _payload_digest(params),
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
        sandbox_workspace_root=workspace_root,
    )

    result = engine.execute_sandbox_adapter_operation(
        operation, {"adapter_params": params}
    )

    adapter_result = result["adapter_result"]
    assert adapter_result["provider_request_id"].startswith("provider_req_")
    bounded_summary = adapter_result["bounded_summary"]
    assert bounded_summary["pdb_id"] == "6LEH"
    assert bounded_summary["format"] == "pdb"
    manifest = bounded_summary["artifacts"][0]
    assert manifest["provider"] == "rcsb_pdb"
    assert manifest["external_id"] == "6LEH"
    assert manifest["content_digest"].startswith("sha256:")
    assert manifest["sealed_digest"] == manifest["content_digest"]
    assert manifest["provenance"]["provider"] == "rcsb_pdb"
    assert "storage_uri" not in json.dumps(manifest)
    artifact = repositories.artifacts.get(str(manifest["artifact_id"]))
    assert artifact is not None
    assert artifact.kind is ArtifactKind.STRUCTURE
    assert artifact.metadata is not None
    assert artifact.metadata["controlled_operation_id"] == operation.operation_id
    assert artifact.metadata["content_digest"] == artifact.metadata["sealed_digest"]
    assert artifact.metadata["provider_provenance"]["external_id"] == "6LEH"


def test_sandbox_adapter_executor_runs_bio_tools_hpc_and_fetches_outputs(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    workspace_root = tmp_path / "workspaces"
    sandbox_workspace_id = _seed_sandbox_adapter_workspace(
        repositories,
        workspace_root=workspace_root,
    )
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_sandbox_hpc_fasta")
    workspace = _workspace_payload("sandbox_hpc")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    params = {
        "input_fasta": staged_fasta,
        "placement": workspace,
        "expected_outputs": _bio_tool_outputs("bio_tools.mafft"),
        "params": {},
    }
    operation = ControlledOperation(
        operation_id="op_sandbox_hpc_mafft",
        session_id="sess_001",
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id="srun_sandbox_hpc_mafft",
        logical_operation_key="bio_tools.mafft",
        operation_digest="sha256:operation-hpc",
        params_digest=_payload_digest(params),
        backend_category="hpc",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-05-31T00:00:01+00:00",
        updated_at="2026-05-31T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_state="approved",
        route_reason="static_policy:v1",
        input_artifact_ids=(fasta_artifact_id,),
        input_artifact_digests=(_artifact_digest(repositories, fasta_artifact_id),),
        source_snapshot_artifact_id="art_source_snapshot",
        source_snapshot_digest="sha256:source",
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio_tools",
        function_name="mafft",
        route_policy_id="bio_tools.mafft.hpc:v1",
        placement="hpc",
        hpc_workspace_id=str(workspace["hpc_workspace_id"]),
        selected_backend="hpc",
        resource_class="hpc_batch_small",
        runtime_packaging_id="hpc_apptainer_sif.aox_hmm_2026_05_30",
        toolchain_id="mafft_7.520.hpc_apptainer_sif:v1",
        stage_refs=(staged_fasta,),
        expected_outputs_summary={
            "declared_outputs": _bio_tool_outputs("bio_tools.mafft")
        },
        resource_estimate={"placement": "hpc", "resource_class": "hpc_batch_small"},
        idempotency_key="bio_tools.mafft:" + _payload_digest(params),
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    repositories.controlled_operations.save(operation)
    source_path = workspace_root / sandbox_workspace_id / "src" / "pipeline.py"
    source_path.write_text(
        "from openzyme_pipeline import bio_tools\n# later unrelated snapshot\n",
        encoding="utf-8",
    )
    later_snapshot = ArtifactBoundaryService(
        repositories,
        workspace_root=workspace_root,
    ).snapshot_code(
        session_id="sess_001",
        sandbox_workspace_id=sandbox_workspace_id,
        paths=["pipeline.py"],
        entrypoint="pipeline.py",
        metadata={"producer": "test-later"},
    )
    assert later_snapshot.artifact.artifact_id != operation.source_snapshot_artifact_id
    runner = ToolchainIdentitySuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_workspace_root=workspace_root,
    )

    result = engine.execute_sandbox_adapter_operation(
        operation,
        {
            "adapter_params": params,
            "_durable_backend_handle_ref": "reserved_runner_hpc_001",
        },
    )

    run_handle = result["result_summary"]
    assert run_handle["kind"] == "hpc_run_handle"
    assert run_handle["operation_id"] == operation.operation_id
    assert run_handle["runner_run_id"] == "reserved_runner_hpc_001"
    assert runner.reserved_run_id == "reserved_runner_hpc_001"
    assert (
        run_handle["toolchain_runtime_identity"]
        == TOOLCHAIN_RUNTIME_IDENTITY
    )
    assert "/private/tool.sif" not in json.dumps(run_handle)
    assert "must-not-propagate" not in json.dumps(run_handle)
    adapter_result = result["adapter_result"]
    assert adapter_result["backend_run_id"] == run_handle["runner_run_id"]
    assert (
        adapter_result["bounded_summary"]["toolchain_runtime_identity"]
        == TOOLCHAIN_RUNTIME_IDENTITY
    )
    assert adapter_result["registered_artifact_ids"] == []
    @contextmanager
    def stale_runtime_scope():  # type: ignore[no-untyped-def]
        raise AssertionError("sandbox-owned fetch reused the stale agent runtime scope")
        yield

    engine.repository_scope_factory = stale_runtime_scope
    fetch = engine.fetch_sandbox_hpc_outputs(
        {
            "session_id": "sess_001",
            "sandbox_workspace_id": sandbox_workspace_id,
            "hpc_workspace": workspace,
            "run_id": run_handle["run_id"],
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
        },
        repositories=repositories,
    )

    assert fetch["kind"] == "hpc_fetch_result"
    assert fetch["registered_artifact_ids"]
    artifacts = repositories.artifacts.list_by_run(str(run_handle["run_id"]))
    assert {artifact.artifact_id for artifact in artifacts} == set(
        fetch["registered_artifact_ids"]
    )
    assert {artifact.relative_path for artifact in artifacts} == {
        "bio_tools/mafft/alignment.fasta"
    }
    artifact = artifacts[0]
    assert artifact.metadata is not None
    assert artifact.metadata["source"] == "sandbox_artifact_boundary"
    assert artifact.metadata["controlled_operation_id"] == operation.operation_id
    assert (
        artifact.metadata["controlled_operation_digest"]
        == operation.operation_digest
    )
    assert (
        artifact.metadata["pipeline_invocation_id"]
        == "inv_sandbox_adapter_op_sandbox_hpc_mafft"
    )
    assert artifact.metadata["sdk_method"] == "bio_tools.mafft"
    assert (
        artifact.metadata["source_snapshot_artifact_id"]
        == operation.source_snapshot_artifact_id
    )
    assert artifact.metadata["source_tree_digest"] == operation.source_snapshot_digest
    assert (
        dict(artifact.metadata["provenance"])["source_snapshot_artifact_id"]
        == operation.source_snapshot_artifact_id
    )


def test_sandbox_adapter_executor_rejects_mutated_sealed_input_before_hpc_submit(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    sandbox_workspace_id = _seed_sandbox_adapter_workspace(
        repositories,
        workspace_root=tmp_path / "workspaces",
        sandbox_workspace_id="sws_adapter_corrupt_input",
    )
    fasta_artifact_id = _save_fasta_artifact(
        repositories,
        "art_sandbox_hpc_corrupt_fasta",
    )
    workspace = _workspace_payload("sandbox_hpc_corrupt")
    staged_fasta = _stage_payload(
        repositories,
        fasta_artifact_id,
        workspace,
        "inputs/sequences.fasta",
    )
    params = {
        "input_fasta": staged_fasta,
        "placement": workspace,
        "expected_outputs": _bio_tool_outputs("bio_tools.mafft"),
        "params": {},
    }
    operation = ControlledOperation(
        operation_id="op_sandbox_hpc_mafft_corrupt_input",
        session_id="sess_001",
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id="srun_sandbox_hpc_mafft_corrupt_input",
        logical_operation_key="bio_tools.mafft",
        operation_digest="sha256:operation-hpc-corrupt-input",
        params_digest=_payload_digest(params),
        backend_category="hpc",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-05-31T00:00:01+00:00",
        updated_at="2026-05-31T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_state="approved",
        route_reason="static_policy:v1",
        input_artifact_ids=(fasta_artifact_id,),
        input_artifact_digests=(
            _artifact_digest(repositories, fasta_artifact_id),
        ),
        source_snapshot_artifact_id="art_source_snapshot",
        source_snapshot_digest="sha256:source",
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio_tools",
        function_name="mafft",
        route_policy_id="bio_tools.mafft.hpc:v1",
        placement="hpc",
        hpc_workspace_id=str(workspace["hpc_workspace_id"]),
        selected_backend="hpc",
        resource_class="hpc_batch_small",
        runtime_packaging_id="hpc_apptainer_sif.aox_hmm_2026_05_30",
        toolchain_id="mafft_7.520.hpc_apptainer_sif:v1",
        stage_refs=(staged_fasta,),
        expected_outputs_summary={
            "declared_outputs": _bio_tool_outputs("bio_tools.mafft")
        },
        resource_estimate={
            "placement": "hpc",
            "resource_class": "hpc_batch_small",
        },
        idempotency_key="bio_tools.mafft:" + _payload_digest(params),
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    artifact = repositories.artifacts.get(fasta_artifact_id)
    assert artifact is not None
    blob_path = Path(artifact.storage_uri)
    original = blob_path.read_bytes()
    mutated = bytearray(original)
    mutated[min(4, len(mutated) - 1)] ^= 1
    blob_path.write_bytes(bytes(mutated))
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_workspace_root=tmp_path / "workspaces",
        artifact_blob_root=tmp_path / "artifact-blobs",
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        engine.execute_sandbox_adapter_operation(
            operation,
            {"adapter_params": params},
        )

    assert exc_info.value.error_type == "artifact_blob_digest_mismatch"
    assert exc_info.value.stage == "adapter_input_integrity"
    assert exc_info.value.details["artifact_id"] == fasta_artifact_id
    assert runner.payloads == []


def test_sandbox_adapter_executor_runs_structure_tools_fpocket_hpc_controlled_operation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    workspace_root = tmp_path / "workspaces"
    sandbox_workspace_id = _seed_sandbox_adapter_workspace(
        repositories,
        workspace_root=workspace_root,
    )
    workspace = _workspace_payload("sandbox_fpocket")
    staged_structure = _stage_payload(
        repositories, "art_001", workspace, "inputs/structure.pdb"
    )
    params = {
        "structure": staged_structure,
        "placement": workspace,
        "expected_outputs": FPOCKET_EXPECTED_OUTPUTS,
        "params": {},
    }
    runner = CapturingSuccessRunner()
    operation = ControlledOperation(
        operation_id="op_sandbox_hpc_fpocket",
        session_id="sess_001",
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id="srun_sandbox_hpc_fpocket",
        logical_operation_key="structure_tools.fpocket",
        operation_digest="sha256:operation-fpocket",
        params_digest=_payload_digest(params),
        backend_category="hpc",
        status=ControlledOperationStatus.RUNNING,
        created_at="2026-05-31T00:00:01+00:00",
        updated_at="2026-05-31T00:00:01+00:00",
        task_id="task_001",
        lane_id="lane_001",
        approval_state="approved",
        route_reason="static_policy:v1",
        input_artifact_ids=("art_001",),
        input_artifact_digests=(_artifact_digest(repositories, "art_001"),),
        source_snapshot_artifact_id="art_source_snapshot",
        source_snapshot_digest="sha256:source",
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="structure_tools",
        function_name="fpocket",
        route_policy_id="structure_tools.fpocket.hpc:v1",
        placement="hpc",
        hpc_workspace_id=str(workspace["hpc_workspace_id"]),
        selected_backend="hpc",
        resource_class="hpc_batch_small",
        runtime_packaging_id="hpc_apptainer_sif.fpocket_2026_05_30",
        toolchain_id="fpocket_4.2.2.hpc_apptainer_sif:v1",
        stage_refs=(staged_structure,),
        expected_outputs_summary={"items": FPOCKET_EXPECTED_OUTPUTS},
        resource_estimate={"placement": "hpc", "resource_class": "hpc_batch_small"},
        planned_fetch_intent={"declared_outputs": FPOCKET_EXPECTED_OUTPUTS},
        idempotency_key="structure_tools.fpocket:" + _payload_digest(params),
    )
    _seed_sandbox_adapter_run(
        repositories,
        sandbox_workspace_id=sandbox_workspace_id,
        sandbox_run_id=operation.sandbox_run_id,
    )
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_workspace_root=workspace_root,
    )

    result = engine.execute_sandbox_adapter_operation(
        operation, {"adapter_params": params}
    )

    run_handle = result["result_summary"]
    assert run_handle["kind"] == "hpc_run_handle"
    assert run_handle["operation_id"] == operation.operation_id
    assert run_handle["route_policy_id"] == "structure_tools.fpocket.hpc:v1"
    assert run_handle["hpc_workspace_id"] == workspace["hpc_workspace_id"]
    assert run_handle["stage_refs"][0]["artifact_id"] == "art_001"
    assert run_handle["stage_refs"][0]["artifact_digest"] == _artifact_digest(
        repositories, "art_001"
    )
    assert run_handle["declared_outputs"] == FPOCKET_EXPECTED_OUTPUTS
    assert len(runner.payloads) == 1
    runspec = runner.payloads[0]["runspec"]
    tool_inputs = dict(runspec["metadata"]["tool_inputs"])
    assert tool_inputs["structure_artifact_id"] == "art_001"
    assert tool_inputs["route_policy_id"] == "structure_tools.fpocket.hpc:v1"
    assert tool_inputs["runtime_packaging_id"] == "hpc_apptainer_sif.fpocket_2026_05_30"
    assert tool_inputs["toolchain_id"] == "fpocket_4.2.2.hpc_apptainer_sif:v1"
    assert tool_inputs["hpc_workspace_id"] == workspace["hpc_workspace_id"]
    assert "storage_uri" not in str(result)
    assert "/tmp/input_structure.pdb" not in str(run_handle)


def test_pipeline_bio_requires_output_dir_before_approval() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_missing_output_dir",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'])\n",
    )
    sandbox = BioSandboxRunner(
        (("bio.ncbi_fetch_proteins", {"accessions": ["P12345"], "fields": []}),)
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_missing_output_dir",
        code_artifact_id=code_artifact_id,
        inputs={},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.approval is None
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "provider_output_path_invalid"
    assert repositories.approvals.list_by_session("sess_001") == []
    assert (
        repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_missing_output_dir"
        )
        == []
    )


def test_pipeline_bio_product_path_without_provider_does_not_use_fixture() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_no_provider",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'], output_dir='/workspace/output/bio/ncbi')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.ncbi_fetch_proteins",
                {
                    "accessions": ["P12345"],
                    "fields": [],
                    "output_dir": "/workspace/output/bio/ncbi",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_no_provider",
        code_artifact_id=code_artifact_id,
        inputs={"approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_no_provider", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "provider_not_configured"
    assert (
        repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_no_provider"
        )
        == []
    )


def test_pipeline_bio_approval_and_result_envelopes_keep_s12_field_placement() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_s12_envelope",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'], output_dir='/workspace/output/bio/ncbi-envelope')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.ncbi_fetch_proteins",
                {
                    "accessions": ["P12345"],
                    "fields": [],
                    "output_dir": "/workspace/output/bio/ncbi-envelope",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_s12_envelope",
        code_artifact_id=code_artifact_id,
        inputs={},
    )

    assert first.approval is not None
    assert first.approval.kind == "execution_pipeline_plan"
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_s12_envelope",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    document = repositories.engine_documents.list_by_invocation(
        "sess_001", "inv_pipeline_bio_s12_envelope"
    )[0]
    envelopes = document.payload["pipeline"]["adapter_approval_envelopes"]
    assert len(envelopes) == 1
    approval_envelope = next(iter(envelopes.values()))
    assert (
        approval_envelope["adapter_envelope_schema_version"]
        == "s12.adapter_envelope.v1"
    )
    assert approval_envelope["sdk_module"] == "bio"
    assert approval_envelope["function_name"] == "ncbi_fetch_proteins"
    assert approval_envelope["route_policy_id"] == "bio.ncbi_fetch_proteins.provider:v1"
    assert approval_envelope["selected_backend"] == "provider_http"
    assert approval_envelope["runtime_packaging_id"] == "provider_http:v1"
    assert approval_envelope["provider_config_digest"] == "provider_config:ncbi:v1"
    assert approval_envelope["planned_output_path_summary"] == {
        "output_dir": "/workspace/output/bio/ncbi-envelope"
    }
    assert approval_envelope["approval_requirement"] == {"required": True}
    assert (
        approval_envelope["expected_outputs"][0]["path"]
        == "<output_dir>/provider_request.json"
    )
    assert "params_digest" in approval_envelope
    assert approval_envelope["approval_source"] == "execution_pipeline_plan"
    assert approval_envelope["approved_plan_digest"]
    assert "provider_request_id" not in approval_envelope
    assert "registered_artifact_ids" not in approval_envelope
    assert "transcript_manifest" not in approval_envelope

    payload = sandbox.results[0]
    result_envelope = payload["adapter_result_envelope"]
    assert "transcript_manifest" not in result_envelope
    assert "transcript_manifest" in result_envelope["bounded_summary"]
    assert result_envelope["bounded_summary"]["transcript_manifest"][
        "route_policy_id"
    ] == ("bio.ncbi_fetch_proteins.provider:v1")
    assert result_envelope["provider_request_id"]
    assert (
        result_envelope["registered_artifact_ids"]
        == result_envelope["output_artifact_ids"]
    )


def test_pipeline_bio_sanitizes_provider_transcript_outputs() -> None:
    class SensitiveAdapter:
        def ncbi_fetch_proteins(self, *, accessions, fields, retrieved_at):  # type: ignore[no-untyped-def]
            del accessions, fields
            return BioSdkResult(
                provider="ncbi",
                operation="bio.ncbi_fetch_proteins",
                summary={"provider": "ncbi", "record_count": 1},
                provider_observation={
                    "headers": {
                        "authorization": "Bearer secret-token",
                        "x-request-id": "req-1",
                    },
                    "host_path": "/tmp/private/cache",
                },
                artifacts=(
                    BioArtifactDraft(
                        relative_path="provider_raw/provider.json",
                        kind=ArtifactKind.RESULT,
                        title="provider.json",
                        content=json.dumps(
                            {
                                "token": "secret-token",
                                "storage_uri": "/tmp/private/raw.json",
                                "message": "valid provider payload",
                            }
                        ),
                        format="json",
                        metadata={
                            "format": "json",
                            "provider": "ncbi",
                            "retrieved_at": retrieved_at,
                        },
                    ),
                ),
                api_version="test",
            )

    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_sanitize",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'], output_dir='/workspace/output/bio/sanitize')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.ncbi_fetch_proteins",
                {
                    "accessions": ["P12345"],
                    "fields": [],
                    "output_dir": "/workspace/output/bio/sanitize",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=SensitiveAdapter(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_sanitize",
        code_artifact_id=code_artifact_id,
        inputs={"approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_sanitize", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    raw_artifact = next(
        artifact
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_sanitize"
        )
        if artifact.relative_path == "bio/sanitize/provider_raw/provider.json"
    )
    observation = next(
        artifact
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_sanitize"
        )
        if artifact.relative_path == "bio/sanitize/provider_observation.json"
    )
    raw_text = Path(raw_artifact.storage_uri).read_text(encoding="utf-8")
    observation_text = Path(observation.storage_uri).read_text(encoding="utf-8")
    assert "secret-token" not in raw_text
    assert "secret-token" not in observation_text
    assert "/tmp/private" not in raw_text
    assert "/tmp/private" not in observation_text
    assert "req-1" in observation_text


def test_pipeline_bio_preserves_validated_raw_provider_bytes() -> None:
    response_body = ">P12345 exact provider bytes\nMSEQUENCE\n"
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ncbi_email="operator@example.test"),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=response_body,
            headers={"x-request-id": "ncbi-exact-1"},
        ),
        sleep=lambda _seconds: None,
    )
    repositories = _build_repositories()
    _seed_session(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_raw_closure",
        "from openzyme_pipeline import bio\n"
        "bio.ncbi_fetch_proteins(accessions=['P12345'], output_dir='/workspace/output/bio/raw-closure')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.ncbi_fetch_proteins",
                {
                    "accessions": ["P12345"],
                    "fields": [],
                    "output_dir": "/workspace/output/bio/raw-closure",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=adapter,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_raw_closure",
        code_artifact_id=code_artifact_id,
        inputs={"approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_raw_closure",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    raw_artifact = next(
        artifact
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_raw_closure"
        )
        if artifact.relative_path
        == "bio/raw-closure/provider_raw/ncbi_efetch.response.json"
    )
    envelope = json.loads(Path(raw_artifact.storage_uri).read_text(encoding="utf-8"))
    response = envelope["responses"][0]
    decoded = base64.b64decode(response["body_base64"], validate=True)
    assert decoded == response_body.encode("utf-8")
    assert response["body_digest"] == _content_digest(response_body)
    assert response["size_bytes"] == len(decoded)


def test_provider_http_bio_adapter_ncbi_fetches_fasta_with_identity() -> None:
    calls: list[tuple[str, str]] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        calls.append((request.full_url, request.get_method()))
        return FakeHttpResponse(
            headers={"x-ratelimit-limit": "3", "authorization": "Bearer secret"},
            body=">P12345 example protein\nMSEQUENCE\n",
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ncbi_email="operator@example.test"),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    result = adapter.ncbi_fetch_proteins(
        accessions=("P12345",),
        fields=("definition",),
        retrieved_at="2026-05-30T00:00:00+00:00",
    )

    assert calls and calls[0][1] == "GET"
    assert "email=operator%40example.test" in calls[0][0]
    assert result.summary["record_count"] == 1
    assert {artifact.relative_path for artifact in result.artifacts} == {
        "provider_raw/ncbi_efetch.response.json",
        "provider_parsed/proteins.fasta",
        "provider_parsed/proteins.metadata.json",
    }
    observation = result.provider_observation or {}
    headers = observation["requests"][0]["headers"]
    assert headers["x-ratelimit-limit"] == "3"
    assert "authorization" not in headers


def test_provider_http_bio_adapter_uniprot_empty_results_fail_closed() -> None:
    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        del request, timeout
        return FakeHttpResponse(
            headers={"x-uniprot-release": "2026_01"}, body='{"results":[]}'
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("Q8XYZ1",),
            fields=("length", "taxonomy"),
            batch_size=50,
            retrieved_at="2026-05-30T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_empty_result"
    assert exc_info.value.retryable is False


def test_provider_http_bio_adapter_hmmer_submit_poll_and_parse_hits() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_provider_http")
    hmm_artifact = repositories.artifacts.get(hmm_artifact_id)
    assert hmm_artifact is not None
    calls: list[str] = []
    form_bodies: list[bytes] = []
    result_polls = 0

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        nonlocal result_polls
        del timeout
        url = request.full_url
        calls.append(url)
        if request.get_method() == "POST":
            form_bodies.append(request.data)
            return FakeHttpResponse(
                body='{"id":"fdaf751e-bf95-4e6a-a70a-6eadf2078ae2"}'
            )
        assert "/result/fdaf751e-bf95-4e6a-a70a-6eadf2078ae2?" in url
        assert "page=1" in url
        assert "page_size=1000" in url
        result_polls += 1
        if result_polls == 1:
            return FakeHttpResponse(
                body='{"status":"STARTED","result":null,"page_count":null}'
            )
        return FakeHttpResponse(
            body=json.dumps(
                {
                    "status": "SUCCESS",
                    "database": "refprot",
                    "number_of_hits": 1,
                    "page_count": 1,
                    "result": {
                        "stats": {"nreported": 2},
                        "hits": [
                            {
                                "name": "hit1",
                                "acc": None,
                                "evalue": 1e-42,
                                "score": 1834.7,
                                "metadata": {
                                    "uniprot_accession": "P12345",
                                    "accession": "P12345",
                                },
                            },
                            {
                                "name": "hit2",
                                "acc": None,
                                "evalue": 0.0,
                                "score": 3153.7,
                                "metadata": {
                                    "uniprot_accession": "Q8XYZ1",
                                    "accession": "Q8XYZ1",
                                },
                            },
                        ]
                    },
                }
            )
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ebi_hmmer_email="operator@example.test"),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    result = adapter.hmmer_search(
        hmm_artifact=hmm_artifact,
        database="refprot",
        params={"evalue": "1e-20"},
        retrieved_at="2026-05-30T00:00:00+00:00",
    )

    assert any(
        "/search/hmmsearch?" in url or url.endswith("/search/hmmsearch")
        for url in calls
    )
    assert result_polls == 3
    assert form_bodies
    submit_payload = json.loads(form_bodies[0].decode("utf-8"))
    assert submit_payload["database"] == "refprot"
    assert submit_payload["input"].startswith("HMMER3/f")
    assert submit_payload["E"] == 1e-20
    assert submit_payload["email_address"] == "operator@example.test"
    assert "email" not in submit_payload
    assert result.summary["hit_count"] == 2
    assert result.summary["provider_job_id"] == "fdaf751e-bf95-4e6a-a70a-6eadf2078ae2"
    parsed = next(
        artifact
        for artifact in result.artifacts
        if artifact.relative_path == "provider_parsed/parsed_hits.csv"
    )
    assert "hit1,P12345,1e-42,1834.7" in parsed.content
    assert "hit2,Q8XYZ1,0.0,3153.7" in parsed.content


def test_provider_http_bio_adapter_hmmer_honors_bounded_max_hits() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact = repositories.artifacts.get(_save_hmm_artifact(repositories))
    assert hmm_artifact is not None
    calls: list[str] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        url = request.full_url
        calls.append(url)
        if request.get_method() == "POST":
            return FakeHttpResponse(
                body='{"id":"fdaf751e-bf95-4e6a-a70a-6eadf2078ae2"}'
            )
        assert "/result/fdaf751e-bf95-4e6a-a70a-6eadf2078ae2?" in url
        assert "page=1" in url
        assert "page_size=2" in url
        return FakeHttpResponse(
            body=json.dumps(
                {
                    "status": "SUCCESS",
                    "database": "refprot",
                    "page_count": 4,
                    "result": {
                        "stats": {"nreported": 8},
                        "hits": [
                            {
                                "name": "hit1",
                                "acc": None,
                                "evalue": 1e-42,
                                "score": 1834.7,
                                "metadata": {"uniprot_accession": "P12345"},
                            },
                            {
                                "name": "hit2",
                                "acc": None,
                                "evalue": 1e-30,
                                "score": 1200.0,
                                "metadata": {"uniprot_accession": "Q8XYZ1"},
                            },
                        ]
                    },
                }
            )
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ebi_hmmer_email="operator@example.test"),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    result = adapter.hmmer_search(
        hmm_artifact=hmm_artifact,
        database="refprot",
        params={"max_hits": 2, "page_size": 2},
        retrieved_at="2026-05-30T00:00:00+00:00",
    )

    assert all("?format=json" in url for url in calls[1:])
    assert result.summary["hit_count"] == 2
    assert result.summary["pagination"]["truncated"] is True
    assert result.summary["pagination"]["max_hits"] == 2
    assert result.summary["pagination"]["page_size"] == 2
    assert any(
        item["warning_code"] == "provider_result_truncated" for item in result.warnings
    )
    truncated_warning = next(
        item
        for item in result.warnings
        if item["warning_code"] == "provider_result_truncated"
    )
    assert truncated_warning["limit"] == 2
    parsed = next(
        artifact
        for artifact in result.artifacts
        if artifact.relative_path == "provider_parsed/parsed_hits.csv"
    )
    assert "hit1,P12345,1e-42,1834.7" in parsed.content
    assert "hit2,Q8XYZ1,1e-30,1200.0" in parsed.content
    assert "hit3" not in parsed.content


def test_provider_http_adapter_retries_remote_disconnect() -> None:
    calls = 0

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        nonlocal calls
        del request, timeout
        calls += 1
        if calls == 1:
            raise http_client.RemoteDisconnected("remote closed")
        return FakeHttpResponse(body=">NP_001230.1\nMSEQ\n")

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ncbi_email="operator@example.test"),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    result = adapter.ncbi_fetch_proteins(
        accessions=("NP_001230.1",),
        fields=(),
        retrieved_at="2026-05-30T00:00:00+00:00",
    )

    assert calls == 2
    assert result.summary["accession_count"] == 1


def test_pipeline_bio_hmmer_search_persists_raw_and_parsed_hits() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_hmmer",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='refprot', output_dir='/workspace/output/bio/hmmer')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "database": "refprot",
                    "params": {"E": 1e-5},
                    "output_dir": "/workspace/output/bio/hmmer",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_hmmer",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id], "approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_hmmer", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["summary"]["hit_count"] == 1
    artifacts = repositories.artifacts.list_by_invocation(
        "sess_001", "inv_pipeline_bio_hmmer"
    )
    paths = {artifact.relative_path for artifact in artifacts}
    assert "bio/hmmer/provider_raw/raw_hits.json" in paths
    assert "bio/hmmer/provider_parsed/parsed_hits.csv" in paths
    assert "bio/hmmer/provider_observation.json" in paths
    parsed = next(
        artifact
        for artifact in artifacts
        if artifact.relative_path == "bio/hmmer/provider_parsed/parsed_hits.csv"
    )
    assert parsed.metadata is not None
    assert parsed.metadata["provider"] == "ebi_hmmer"
    assert parsed.metadata["query_hmm_artifact_id"] == hmm_artifact_id
    assert "fixture_hit_001" in Path(parsed.storage_uri).read_text(encoding="utf-8")


def test_pipeline_bio_hmmer_empty_results_returns_warning() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_empty")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_hmmer_empty",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='empty', output_dir='/workspace/output/bio/hmmer-empty')\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "database": "empty",
                    "params": {},
                    "output_dir": "/workspace/output/bio/hmmer-empty",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_empty",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id], "approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_empty", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["summary"]["hit_count"] == 0
    assert sandbox.results[0]["warnings"][0]["warning_code"] == "empty_results"
    parsed = next(
        artifact
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_empty"
        )
        if artifact.relative_path == "bio/hmmer-empty/provider_parsed/parsed_hits.csv"
    )
    assert (
        Path(parsed.storage_uri).read_text(encoding="utf-8")
        == "target,accession,evalue,score\n"
    )


def test_pipeline_bio_provider_timeout_is_structured_failure() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_timeout")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_timeout",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='refprot', output_dir='/workspace/output/bio/hmmer-timeout', params={{'simulate': 'timeout'}})\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "database": "refprot",
                    "params": {"simulate": "timeout"},
                    "output_dir": "/workspace/output/bio/hmmer-timeout",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_timeout",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id], "approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_timeout", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "provider_timeout"
    assert error["stage"] == "provider_request"
    assert error["retryable"] is True
    assert error["details"]["provider"] == "ebi_hmmer"
    artifacts = repositories.artifacts.list_by_invocation(
        "sess_001", "inv_pipeline_bio_timeout"
    )
    assert "bio/hmmer-timeout/provider_error.json" in {
        artifact.relative_path for artifact in artifacts
    }


@pytest.mark.parametrize(
    ("simulation", "error_type", "stage", "retryable"),
    [
        ("schema_drift", "provider_schema_drift", "provider_response_parse", False),
        ("pagination_failure", "provider_timeout", "provider_pagination", True),
    ],
)
def test_pipeline_bio_schema_and_pagination_failures_are_structured(
    simulation: str,
    error_type: str,
    stage: str,
    retryable: bool,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, f"art_hmm_{simulation}")
    code_artifact_id = _pipeline_source_id(
        repositories,
        f"code_bio_{simulation}",
        "from openzyme_pipeline import bio\n"
        f"bio.hmmer_search(hmm_artifact_id='{hmm_artifact_id}', database='refprot', output_dir='/workspace/output/bio/hmmer-{simulation}', params={{'simulate': '{simulation}'}})\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio.hmmer_search",
                {
                    "hmm_artifact_id": hmm_artifact_id,
                    "database": "refprot",
                    "params": {"simulate": simulation},
                    "output_dir": f"/workspace/output/bio/hmmer-{simulation}",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=sandbox,
        bio_adapter=DeterministicBioDatabaseAdapter(),
        allow_bio_fixture_adapter=True,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id=f"inv_pipeline_bio_{simulation}",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [hmm_artifact_id], "approval_policy": "single_plan"},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id=f"inv_pipeline_bio_{simulation}", resolution="approved"
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == error_type
    assert error["stage"] == stage
    assert error["retryable"] is retryable


def test_deterministic_cdhit_adapter_emits_canonical_non_cutover_membership() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fixture_cdhit")
    fasta_artifact = repositories.artifacts.get(fasta_artifact_id)
    assert fasta_artifact is not None

    result = DeterministicBioToolsAdapter().cdhit(
        input_fasta=fasta_artifact,
        identity=0.9,
        mode="protein",
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    membership = next(
        artifact
        for artifact in result.artifacts
        if artifact.relative_path == "bio_tools/cdhit/clusters.csv"
    )
    assert membership.content.splitlines() == [
        CDHIT_MEMBERSHIP_HEADER,
        "cluster_0,seq1,seq1,true,1.000000,22",
        "cluster_1,seq2,seq2,true,1.000000,22",
    ]
    assert membership.metadata["membership_schema_id"] == "cdhit_cluster_membership@1"
    assert membership.metadata["fixture_classification"] == "deterministic_fixture"
    assert membership.metadata["scientific_status"] == "fixture_non_cutover"
    assert membership.metadata["cutover_eligible"] is False
    assert result.summary["scientific_status"] == "fixture_non_cutover"
    assert result.summary["cutover_eligible"] is False


def test_pipeline_bio_tools_persist_declared_outputs_with_provenance(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories)
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_tools")
    workspace = _workspace_payload()
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    staged_alignment = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/alignment.fasta"
    )
    staged_hmm = _stage_payload(
        repositories, hmm_artifact_id, workspace, "inputs/model.hmm"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools",
        "from openzyme_pipeline import bio_tools, hpc\n"
        "ws = hpc.workspace('aox_hmm')\n"
        f"fasta = ws.stage_artifact('{fasta_artifact_id}', workspace_path='inputs/sequences.fasta')\n"
        f"hmm = ws.stage_artifact('{hmm_artifact_id}', workspace_path='inputs/model.hmm')\n"
        "cdhit = bio_tools.cdhit(input_fasta=fasta, placement=ws, identity=0.9, expected_outputs=[{'path': 'bio_tools/cdhit/clustered.fasta', 'kind': 'sequence'}])\n"
        "bio_tools.mafft(input_fasta=fasta, placement=ws, expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence'}])\n"
        "bio_tools.hmmbuild(alignment=fasta, placement=ws, expected_outputs=[{'path': 'bio_tools/hmmbuild/model.hmm', 'kind': 'result'}])\n"
        "bio_tools.hmmalign(hmm=hmm, fasta=fasta, placement=ws, expected_outputs=[{'path': 'bio_tools/hmmalign/aligned.fasta', 'kind': 'sequence'}])\n",
    )
    sandbox = FetchAfterEachBioToolSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
            (
                "bio_tools.mafft",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.mafft"),
                    "params": {},
                },
            ),
            (
                "bio_tools.hmmbuild",
                {
                    "alignment": staged_alignment,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.hmmbuild"),
                    "params": {},
                },
            ),
            (
                "bio_tools.hmmalign",
                {
                    "hmm": staged_hmm,
                    "fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.hmmalign"),
                    "params": {},
                },
            ),
        ),
        workspace,
    )
    runner = CapturingSuccessRunner()
    sandbox_root = tmp_path / "blank-sandboxes"
    blob_root = tmp_path / "blank-blobs"
    engine = ExecutionEngine(
        repositories,
        runner,
        sandbox_runner=sandbox,
        sandbox_workspace_root=sandbox_root,
        artifact_blob_root=blob_root,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    assert runner.payloads == []
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_tools",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert len(runner.payloads) == 4
    assert [
        dict(payload["runspec"])["metadata"]["catalog_tool_id"]
        for payload in runner.payloads
    ] == [
        "bio_tools.cdhit",
        "bio_tools.mafft",
        "bio_tools.hmmbuild",
        "bio_tools.hmmalign",
    ]
    assert (
        dict(runner.payloads[0]["runspec"])["inputs"][0]["remote_path"] == "input.fasta"
    )
    assert "storage_uri" not in str(
        runner.payloads[0]["runspec"]["metadata"].get("tool_inputs", {})
    )
    document = repositories.engine_documents.list_by_invocation(
        "sess_001", "inv_pipeline_bio_tools"
    )[0]
    envelopes = document.payload["pipeline"]["adapter_approval_envelopes"]
    assert len(envelopes) == 4
    cdhit_envelope = next(
        envelope
        for envelope in envelopes.values()
        if envelope["function_name"] == "cdhit"
    )
    assert cdhit_envelope["route_policy_id"] == "bio_tools.cdhit.hpc:v1"
    assert cdhit_envelope["selected_backend"] == "hpc"
    assert (
        cdhit_envelope["runtime_packaging_id"] == "hpc_apptainer_sif.aox_hmm_2026_05_30"
    )
    assert cdhit_envelope["toolchain_id"] == "cdhit_4.8.1.hpc_apptainer_sif:v1"
    assert cdhit_envelope["hpc_workspace_id"] == workspace["hpc_workspace_id"]
    assert cdhit_envelope["planned_fetch_intent"] is True
    assert cdhit_envelope["approval_source"] == "execution_pipeline_plan"
    assert len(sandbox.results) == 8
    assert sandbox.results[0]["kind"] == "hpc_run_handle"
    assert sandbox.results[1]["kind"] == "hpc_fetch_result"
    assert "artifact_ids" not in sandbox.results[0]
    assert "artifact_count" not in sandbox.results[0]
    artifacts = repositories.artifacts.list_by_invocation(
        "sess_001", "inv_pipeline_bio_tools"
    )
    paths = {artifact.relative_path for artifact in artifacts}
    assert {
        "bio_tools/cdhit/clustered.fasta",
        "bio_tools/cdhit/clusters.csv",
        "bio_tools/mafft/alignment.fasta",
        "bio_tools/hmmbuild/model.hmm",
        "bio_tools/hmmalign/aligned.fasta",
    }.issubset(paths)
    clustered = next(
        artifact
        for artifact in artifacts
        if artifact.relative_path == "bio_tools/cdhit/clustered.fasta"
    )
    assert clustered.metadata is not None
    assert clustered.metadata["source"] == "sandbox_artifact_boundary"
    assert clustered.metadata["catalog_tool_id"] == "bio_tools.cdhit"
    assert (
        clustered.metadata["tool_inputs"]["route_policy_id"] == "bio_tools.cdhit.hpc:v1"
    )
    assert clustered.metadata["source_code_artifact_id"] == code_artifact_id
    membership = next(
        artifact
        for artifact in artifacts
        if artifact.relative_path == "bio_tools/cdhit/clusters.csv"
    )
    assert membership.metadata is not None
    assert membership.metadata["membership_schema_id"] == "cdhit_cluster_membership@1"
    assert membership.metadata["membership_columns"] == [
        "cluster_id",
        "member_id",
        "representative_id",
        "is_representative",
        "identity_to_representative",
        "member_length",
    ]
    assert membership.metadata["row_semantics"] == "one_member_per_row"
    assert all(
        Path(artifact.storage_uri).is_relative_to(blob_root) for artifact in artifacts
    )
    assert any(blob_root.rglob("*"))
    assert any(sandbox_root.rglob("*"))


def test_pipeline_bio_tools_runner_and_invalid_input_failures_are_structured() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fasta_fail")
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_fail")
    workspace = _workspace_payload("aox_fail")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    staged_invalid_fasta = _stage_payload(
        repositories, "art_001", workspace, "inputs/not_fasta.pdb"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_failure",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture supplies placement-aware bio_tools calls.\n",
    )
    failed_runner = CapturingFailedRunner()
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.mafft",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.mafft"),
                    "params": {},
                },
            ),
        )
    )
    engine = ExecutionEngine(repositories, failed_runner, sandbox_runner=sandbox)
    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools_runner_failure",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
        idempotency_key="case:runner_failure",
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    failed = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_tools_runner_failure",
        resolution="approved",
    )
    assert failed.invocation.status is EngineInvocationStatus.FAILED
    assert failed.parsed_result is not None
    runner_error = failed.parsed_result.structured_findings["error"]
    assert runner_error["type"] == "container_runtime_missing"
    assert runner_error["stage"] == "remote_execution"
    assert runner_error["hpc_failure"]["error_code"] == "APPTAINER_MISSING"

    invalid_sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_invalid_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
        )
    )
    invalid_runner = CapturingSuccessRunner()
    invalid_engine = ExecutionEngine(
        repositories, invalid_runner, sandbox_runner=invalid_sandbox
    )
    invalid = invalid_engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools_invalid_fasta",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
        idempotency_key="case:invalid_fasta",
    )
    assert invalid.invocation.status is EngineInvocationStatus.FAILED
    assert invalid.parsed_result is not None
    error = invalid.parsed_result.structured_findings["error"]
    assert error["type"] == "invalid_fasta"
    assert error["stage"] == "bio_tools_input_validation"
    assert invalid_runner.payloads == []


@pytest.mark.parametrize(
    ("runner_code", "expected_error_type", "expected_retryable"),
    [
        ("SSH_CONNECTION_TIMEOUT", "hpc_runner_timeout", True),
        ("SSH_CONNECTION_FAILED", "hpc_runner_unavailable", True),
        ("RUN_FAILED", "nonzero_exit", False),
    ],
)
def test_pipeline_bio_tools_runner_failures_preserve_taxonomy(
    runner_code: str,
    expected_error_type: str,
    expected_retryable: bool,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(
        repositories, f"art_fasta_{runner_code.lower()}"
    )
    workspace = _workspace_payload(f"transport_{runner_code.lower()}")
    staged_fasta = _stage_payload(
        repositories,
        fasta_artifact_id,
        workspace,
        "inputs/sequences.fasta",
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        f"code_{runner_code.lower()}",
        "from openzyme_pipeline import bio_tools\n",
    )
    runner = CapturingTransportFailedRunner(runner_code)
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.mafft",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.mafft"),
                    "params": {},
                },
            ),
        )
    )
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id=f"inv_{runner_code.lower()}",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)

    failed = engine.continue_after_approval(
        invocation_id=f"inv_{runner_code.lower()}",
        resolution="approved",
    )

    assert failed.invocation.status is EngineInvocationStatus.FAILED
    assert failed.parsed_result is not None
    error = failed.parsed_result.structured_findings["error"]
    assert error["type"] == expected_error_type
    assert error["stage"] == "remote_execution"
    assert error["retryable"] is expected_retryable
    assert error["hpc_failure"]["error_code"] == runner_code


def test_pipeline_bio_tools_real_runner_stack_projects_transport_timeout_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_hpc_runner.preflight import PreflightResult
    from mcp_hpc_runner.remote import CommandResult
    from mcp_hpc_runner.server import MCPHpcServer
    from openzyme_execution import HpcRunnerExecutionAdapter

    config_path = tmp_path / "hpc-runner.toml"
    runner_artifact_root = tmp_path / "runner-artifacts"
    config_path.write_text(
        "\n".join(
            [
                "[cluster]",
                'ssh_host = "private-runner.invalid"',
                'remote_base_dir = "mcp_runs"',
                "",
                "[execution]",
                f'artifact_root = "{runner_artifact_root}"',
            ]
        ),
        encoding="utf-8",
    )
    server = MCPHpcServer(config_path)
    observed_stages: list[str | None] = []
    private_stderr = (
        "Connection to private-runner.invalid port 22222 timed out\n"
    )

    def fake_command_run(
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:  # noqa: ARG001
        observed_stages.append(stage)
        if stage == "remote_execution":
            return CommandResult(
                args=args,
                returncode=255,
                stdout="",
                stderr=private_stderr,
                stage=stage,
                elapsed_seconds=60.0,
            )
        return CommandResult(
            args=args,
            returncode=0,
            stdout="",
            stderr="",
            stage=stage,
        )

    server.command_runner.run = fake_command_run  # type: ignore[method-assign]
    monkeypatch.setattr(
        "mcp_hpc_runner.ssh_runner.run_preflight",
        lambda *_args, **_kwargs: PreflightResult(checks=[], passed=True),
    )

    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(
        repositories, "art_real_stack_transport"
    )
    workspace = _workspace_payload("real_stack_transport")
    staged_fasta = _stage_payload(
        repositories,
        fasta_artifact_id,
        workspace,
        "inputs/sequences.fasta",
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_real_stack_transport",
        "from openzyme_pipeline import bio_tools\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.mafft",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.mafft"),
                    "params": {},
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories,
        HpcRunnerExecutionAdapter(server=server),
        sandbox_runner=sandbox,
    )
    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_real_stack_transport",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)

    failed = engine.continue_after_approval(
        invocation_id="inv_real_stack_transport",
        resolution="approved",
    )

    assert failed.invocation.status is EngineInvocationStatus.FAILED
    assert failed.parsed_result is not None
    error = failed.parsed_result.structured_findings["error"]
    assert error["type"] == "hpc_operation_failed"
    assert error["stage"] == "remote_execution"
    assert error["retryable"] is False
    assert error["hpc_failure"]["error_code"] == "DISPATCH_IN_DOUBT"
    assert error["hpc_failure"]["phase"] == "dispatching"
    assert error["hpc_failure"]["effect_certainty"] == "dispatch_in_doubt"
    assert error["hpc_failure"]["retry_eligibility"] == "reconcile_required"
    assert error["hpc_failure"]["reconciliation_required"] is True
    assert "stderr_excerpt" not in error["hpc_failure"]
    assert private_stderr.strip() not in str(error)
    assert repositories.artifacts.list_by_invocation(
        "sess_001", "inv_real_stack_transport"
    ) == []
    assert "artifact_fetch" not in observed_stages

    metadata_paths = list(
        runner_artifact_root.glob("*/metadata/run_result_metadata.json")
    )
    assert len(metadata_paths) == 1
    runner_metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
    assert runner_metadata["runner_phase"] == "dispatching"
    assert runner_metadata["effect_certainty"] == "dispatch_in_doubt"
    assert runner_metadata["retry_eligibility"] == "reconcile_required"
    assert runner_metadata["reconciliation_required"] is True


def test_pipeline_bio_tools_missing_declared_output_does_not_synthesize_artifact() -> (
    None
):
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fasta_missing_output")
    workspace = _workspace_payload("aox_missing_output")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_missing_output",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture supplies placement-aware cdhit.\n",
    )
    sandbox = FetchAfterEachBioToolSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
        ),
        workspace,
    )
    runner = MissingDeclaredOutputRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools_missing_output",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_tools_missing_output",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "declared_output_missing"
    assert error["stage"] == "bio_tools_output_validation"
    assert error["details"]["missing_outputs"] == ["bio_tools/cdhit/clusters.csv"]
    assert (
        repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_tools_missing_output"
        )
        == []
    )


@pytest.mark.parametrize(
    ("membership_content", "expected_reason"),
    [
        (
            "cluster_id,representative,member_count\ncluster_0,seq1,2\n",
            "schema_mismatch",
        ),
        (
            f"{CDHIT_MEMBERSHIP_HEADER}\ncluster_0,seq1,seq1,true,1.000000,22\n",
            "membership_input_mismatch",
        ),
        (
            f"{CDHIT_MEMBERSHIP_HEADER}\n"
            "cluster_0,seq1,seq1,true,1.000000,22\n"
            "cluster_0,seq2,seq1,false,0.900000,22\n"
            "cluster_0,seq2,seq1,false,0.900000,22\n",
            "duplicate_membership",
        ),
    ],
    ids=("legacy_aggregate_schema", "missing_member", "duplicate_member"),
)
def test_pipeline_cdhit_membership_fails_closed_before_output_registration(
    membership_content: str,
    expected_reason: str,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(
        repositories, f"art_cdhit_{expected_reason}"
    )
    workspace = _workspace_payload(f"cdhit_{expected_reason}")
    staged_fasta = _stage_payload(
        repositories,
        fasta_artifact_id,
        workspace,
        "inputs/sequences.fasta",
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        f"code_cdhit_{expected_reason}",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture supplies placement-aware cdhit.\n",
    )
    sandbox = FetchAfterEachBioToolSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
        ),
        workspace,
    )
    runner = CdhitMembershipOutputRunner(membership_content)
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    invocation_id = f"inv_pipeline_cdhit_{expected_reason}"

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id=invocation_id,
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id=invocation_id,
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "output_validation_failed"
    assert error["stage"] == "bio_tools_output_validation"
    assert error["details"]["schema_id"] == "cdhit_cluster_membership@1"
    assert error["details"]["reason"] == expected_reason
    output_paths = {
        artifact.relative_path
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", invocation_id
        )
    }
    assert "bio_tools/cdhit/clustered.fasta" not in output_paths
    assert "bio_tools/cdhit/clusters.csv" not in output_paths


def test_pipeline_bio_tools_accepts_hpc_runner_artifact_refs_without_metadata() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fasta_adapter_shape")
    workspace = _workspace_payload("aox_adapter_shape")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_adapter_shape",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture supplies placement-aware cdhit.\n",
    )
    sandbox = FetchAfterEachBioToolSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
        ),
        workspace,
    )
    engine = ExecutionEngine(
        repositories, AdapterShapeSuccessRunner(), sandbox_runner=sandbox
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools_adapter_shape",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_bio_tools_adapter_shape",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    paths = {
        artifact.relative_path
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_tools_adapter_shape"
        )
    }
    assert {"bio_tools/cdhit/clustered.fasta", "bio_tools/cdhit/clusters.csv"}.issubset(
        paths
    )


def test_pipeline_bio_tools_hmmer_search_cli_is_disabled_in_s14() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fasta_disabled")
    hmm_artifact_id = _save_hmm_artifact(repositories, "art_hmm_disabled")
    workspace = _workspace_payload("aox_disabled")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    staged_hmm = _stage_payload(
        repositories, hmm_artifact_id, workspace, "inputs/model.hmm"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_bio_tools_disabled",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture supplies placement-aware hmmer_search_cli.\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.hmmer_search_cli",
                {
                    "hmm": staged_hmm,
                    "target_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.hmmer_search_cli"),
                    "params": {"evalue": "1e-20"},
                },
            ),
        ),
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_bio_tools_disabled",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id, hmm_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert sandbox.results == []
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "unsupported_in_s14"
    assert error["stage"] == "bio_tools_route_policy_validation"
    assert error["retryable"] is False
    assert (
        repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_bio_tools_disabled"
        )
        == []
    )


@pytest.mark.integration
@pytest.mark.live_hpc
def test_s14_bio_tools_product_route_live_hpc_smoke(tmp_path: Path) -> None:
    from mcp_hpc_runner.server import MCPHpcServer
    from openzyme_execution import HpcRunnerExecutionAdapter
    from openzyme_runtime import live_hpc_skip_reason
    from openzyme_runtime import load_current_settings
    from openzyme_engines.podman_sandbox import PodmanPipelineSandboxRunner

    settings = load_current_settings()
    if reason := live_hpc_skip_reason(settings):
        pytest.skip(reason)

    workspace_root = (
        Path("/tmp")
        / f"s14bio_{hashlib.sha256(str(tmp_path).encode()).hexdigest()[:8]}"
    )
    sandbox = PodmanPipelineSandboxRunner(
        timeout_seconds=900, workspace_root=workspace_root
    )
    preflight = sandbox.preflight()
    if not preflight.ok:
        pytest.skip(
            f"S14 product-route live HPC smoke requires pipeline sandbox: {preflight.message}"
        )

    repository_provider = SQLiteRepositoryProvider(
        str(tmp_path / "s14-live-control-plane.sqlite3")
    )
    main_connection = connect_sqlite(repository_provider.database_path)
    repositories = CoreRepositories.from_connection(main_connection)

    @contextmanager
    def repository_scope():
        with repository_provider.connection_scope() as owner:
            yield owner.repositories

    _seed_session(repositories)
    fixture_root = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "mcp-hpc-runner"
        / "fixtures"
        / "hpc_tool_samples"
        / "aox_hmm"
    )
    fixture_artifacts = {
        "art_s14_live_sequences": (
            fixture_root / "input_sequences.fasta",
            "sequences/input_sequences.fasta",
        ),
        "art_s14_live_targets": (
            fixture_root / "search_targets.fasta",
            "sequences/search_targets.fasta",
        ),
    }
    for artifact_id, (fixture_path, relative_path) in fixture_artifacts.items():
        content = fixture_path.read_text(encoding="utf-8")
        repositories.artifacts.save(
            SessionArtifactRecord(
                artifact_id=artifact_id,
                session_id="sess_001",
                task_id="task_001",
                lane_id="lane_001",
                invocation_id="seed_invocation",
                run_id=None,
                kind=ArtifactKind.SEQUENCE,
                storage_uri=str(fixture_path),
                relative_path=relative_path,
                title=fixture_path.name,
                description="S14 committed AOX/HMM smoke fixture.",
                metadata={
                    "source": "s14_live_fixture",
                    "format": "fasta",
                    "content_digest": _content_digest(content),
                },
                created_at="2026-05-30T00:00:00+00:00",
            )
        )

    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_s14_live_bio_tools",
        "from openzyme_pipeline import bio_tools, hpc\n"
        "ws = hpc.workspace('s14_bio_tools_live')\n"
        "sequences = ws.stage_artifact('art_s14_live_sequences', workspace_path='inputs/input_sequences.fasta')\n"
        "targets = ws.stage_artifact('art_s14_live_targets', workspace_path='inputs/search_targets.fasta')\n"
        "cdhit = bio_tools.cdhit(\n"
        "    input_fasta=sequences,\n"
        "    placement=ws,\n"
        "    identity=0.85,\n"
        "    mode='candidate',\n"
        "    expected_outputs=[\n"
        "        {'path': 'bio_tools/cdhit/clustered.fasta', 'kind': 'sequence', 'format': 'fasta'},\n"
        "        {'path': 'bio_tools/cdhit/clusters.csv', 'kind': 'result', 'format': 'csv'},\n"
        "    ],\n"
        ")\n"
        "ws.fetch_outputs(cdhit)\n"
        "mafft = ws.fetch_outputs(bio_tools.mafft(\n"
        "    input_fasta=sequences,\n"
        "    placement=ws,\n"
        "    expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence', 'format': 'fasta'}],\n"
        "))\n"
        "alignment = ws.stage_artifact(mafft['registered_artifact_ids'][0], workspace_path='inputs/alignment.fasta')\n"
        "hmm = ws.fetch_outputs(bio_tools.hmmbuild(\n"
        "    alignment=alignment,\n"
        "    placement=ws,\n"
        "    expected_outputs=[{'path': 'bio_tools/hmmbuild/model.hmm', 'kind': 'result', 'format': 'hmm'}],\n"
        "))\n"
        "model = ws.stage_artifact(hmm['registered_artifact_ids'][0], workspace_path='inputs/model.hmm')\n"
        "ws.fetch_outputs(bio_tools.hmmalign(\n"
        "    hmm=model,\n"
        "    fasta=targets,\n"
        "    placement=ws,\n"
        "    expected_outputs=[{'path': 'bio_tools/hmmalign/aligned.fasta', 'kind': 'sequence', 'format': 'fasta'}],\n"
        "))\n",
    )
    engine = ExecutionEngine(
        repositories,
        HpcRunnerExecutionAdapter(
            config_path=settings.execution.hpc_runner_config,
            server=MCPHpcServer(settings.execution.hpc_runner_config),
        ),
        sandbox_runner=sandbox,
        repository_scope_factory=repository_scope,
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_s14_bio_tools_live_hpc",
        code_artifact_id=code_artifact_id,
        inputs={
            "artifact_ids": ["art_s14_live_sequences", "art_s14_live_targets"],
            "approval_policy": "single_plan",
        },
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    assert first.approval.kind == "execution_pipeline_plan"
    _approve_request(repositories, first.approval)

    result = engine.continue_after_approval(
        invocation_id="inv_s14_bio_tools_live_hpc",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED, (
        None
        if result.parsed_result is None
        else result.parsed_result.structured_findings
    )
    paths = {
        artifact.relative_path
        for artifact in repositories.artifacts.list_by_invocation(
            "sess_001", "inv_s14_bio_tools_live_hpc"
        )
    }
    assert {
        "bio_tools/cdhit/clustered.fasta",
        "bio_tools/cdhit/clusters.csv",
        "bio_tools/mafft/alignment.fasta",
        "bio_tools/hmmbuild/model.hmm",
        "bio_tools/hmmalign/aligned.fasta",
    }.issubset(paths)
    document = repositories.engine_documents.list_by_invocation(
        "sess_001", "inv_s14_bio_tools_live_hpc"
    )[0]
    envelopes = document.payload["pipeline"]["adapter_approval_envelopes"]
    assert {
        envelope["sdk_module"] + "." + envelope["function_name"]
        for envelope in envelopes.values()
    } == {
        "bio_tools.cdhit",
        "bio_tools.mafft",
        "bio_tools.hmmbuild",
        "bio_tools.hmmalign",
    }
    assert all(envelope["selected_backend"] == "hpc" for envelope in envelopes.values())
    assert all(
        envelope["approval_source"] == "execution_pipeline_plan"
        for envelope in envelopes.values()
    )


def test_pipeline_rejects_literal_artifact_get_ids_missing_from_inputs() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=HandlerSandboxRunner()
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_missing_inputs",
        _fpocket_pipeline_code(),
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_infer_artifact",
        code_artifact_id=code_artifact_id,
        inputs={},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    assert (
        result.parsed_result.structured_findings["error"]["error_code"]
        == "missing_pipeline_artifact_inputs"
    )
    assert "art_001" in result.parsed_result.structured_findings["error"]["hint"]


def test_pipeline_supervisor_records_sandbox_preflight_failure() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        ImmediateSuccessRunner(),
        sandbox_runner=HandlerSandboxRunner(preflight_ok=False),
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_preflight_failure",
        "print('hello from sandbox')\n",
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "sandbox_preflight_failed"
    assert error["stage"] == "sandbox_preflight"
    assert error["retryable"] is False


def test_pipeline_fetch_outputs_rejects_register_parameter() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    workspace = _workspace_payload("fetch_register")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_fetch_register",
        "from openzyme_pipeline import hpc\n"
        "# Runtime sandbox fixture calls hpc.fetch_outputs with a removed register parameter.\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "hpc.fetch_outputs",
                {"hpc_workspace": workspace, "run_id": "run_missing", "register": True},
            ),
        )
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_fetch_register",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "hpc_fetch_register_parameter_unsupported"
    assert error["stage"] == "hpc_fetch_validation"
    assert error["sdk_method"] == "hpc.fetch_outputs"


def test_pipeline_stage_artifact_requires_s08_sealed_digest() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    artifact = repositories.artifacts.get("art_001")
    assert artifact is not None
    metadata = dict(artifact.metadata or {})
    metadata.pop("content_digest", None)
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact.artifact_id,
            session_id=artifact.session_id,
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
            invocation_id=artifact.invocation_id,
            run_id=artifact.run_id,
            kind=artifact.kind,
            storage_uri=artifact.storage_uri,
            relative_path=artifact.relative_path,
            title=artifact.title,
            description=artifact.description,
            metadata=metadata,
            created_at=artifact.created_at,
        )
    )
    workspace = _workspace_payload("missing_digest")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_stage_digest_missing",
        "from openzyme_pipeline import hpc\n"
        "# Runtime sandbox fixture calls hpc.stage_artifact.\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "hpc.stage_artifact",
                {
                    "hpc_workspace": workspace,
                    "artifact_id": "art_001",
                    "workspace_path": "inputs/structure.pdb",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_stage_digest_missing",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "hpc_stage_digest_missing"
    assert error["stage"] == "hpc_stage_validation"


def test_pipeline_stage_artifact_accepts_rcsb_downloaded_sealed_artifact() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    register_bio_research_tools(
        registry,
        service=DeterministicBioResearchService(),
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
    )
    download = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_download_rcsb_for_stage",
            tool_name="rcsb_pdb.download_structure",
            arguments={"pdb_id": "1ABC", "format": "pdb"},
            task_id="task_001",
            lane_id="lane_001",
        ),
    )
    assert download.ok is True
    download_payload = json.loads(download.content)
    artifact_id = str(download_payload["artifacts"][0]["artifact_id"])
    artifact = repositories.artifacts.get(artifact_id)
    assert artifact is not None
    metadata = dict(artifact.metadata or {})
    assert metadata["content_digest"] == metadata["sealed_digest"]

    workspace = _workspace_payload("rcsb_download")
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_stage_rcsb_download",
        "from openzyme_pipeline import hpc\n"
        "# Runtime sandbox fixture stages the downloaded RCSB artifact.\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "hpc.stage_artifact",
                {
                    "hpc_workspace": workspace,
                    "artifact_id": artifact_id,
                    "workspace_path": "inputs/structure.pdb",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_stage_rcsb_download",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["artifact_id"] == artifact_id
    assert sandbox.results[0]["artifact_digest"] == metadata["content_digest"]


def test_pipeline_stage_ref_digest_mismatch_is_rejected() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_stage_digest_mismatch")
    workspace = _workspace_payload("digest_mismatch")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    staged_fasta["artifact_digest"] = "sha256:wrong"
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_stage_ref_digest_mismatch",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture supplies a forged staged ref.\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_stage_ref_digest_mismatch",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "artifact_digest_mismatch"
    assert error["stage"] == "hpc_stage_validation"


def test_pipeline_hpc_domain_operation_does_not_eager_persist_artifacts() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_no_eager_fasta")
    workspace = _workspace_payload("no_eager")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_no_eager_persist",
        "from openzyme_pipeline import bio_tools\n"
        "# Runtime sandbox fixture calls bio_tools without fetch_outputs.\n",
    )
    sandbox = BioSandboxRunner(
        (
            (
                "bio_tools.cdhit",
                {
                    "input_fasta": staged_fasta,
                    "placement": workspace,
                    "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
                    "identity": 0.9,
                    "mode": "protein",
                },
            ),
        )
    )
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_no_eager_persist",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_no_eager_persist",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert sandbox.results[0]["kind"] == "hpc_run_handle"
    assert "artifact_ids" not in sandbox.results[0]
    assert "artifact_count" not in sandbox.results[0]
    assert (
        repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_no_eager_persist"
        )
        == []
    )


def test_pipeline_fetch_outputs_registers_declared_outputs_through_artifact_boundary() -> (
    None
):
    repositories = _build_repositories()
    _seed_session(repositories)
    fasta_artifact_id = _save_fasta_artifact(repositories, "art_fetch_boundary_fasta")
    workspace = _workspace_payload("fetch_boundary")
    staged_fasta = _stage_payload(
        repositories, fasta_artifact_id, workspace, "inputs/sequences.fasta"
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_fetch_boundary",
        "from openzyme_pipeline import bio_tools, hpc\n"
        "# Runtime sandbox fixture calls bio_tools then hpc.fetch_outputs.\n",
    )
    operation = (
        "bio_tools.cdhit",
        {
            "input_fasta": staged_fasta,
            "placement": workspace,
            "expected_outputs": _bio_tool_outputs("bio_tools.cdhit"),
            "identity": 0.9,
            "mode": "protein",
        },
    )
    sandbox = FetchAfterBioToolSandboxRunner(operation, workspace)
    engine = ExecutionEngine(
        repositories, ImmediateSuccessRunner(), sandbox_runner=sandbox
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_fetch_boundary",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": [fasta_artifact_id]},
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_fetch_boundary",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    run = sandbox.results[0]
    fetch = sandbox.results[1]
    assert run["kind"] == "hpc_run_handle"
    assert fetch["kind"] == "hpc_fetch_result"
    assert fetch["registered_artifact_ids"]
    artifacts = repositories.artifacts.list_by_run(str(run["run_id"]))
    assert {artifact.artifact_id for artifact in artifacts} == set(
        fetch["registered_artifact_ids"]
    )
    assert {artifact.relative_path for artifact in artifacts} == {
        "bio_tools/cdhit/clustered.fasta",
        "bio_tools/cdhit/clusters.csv",
    }
    for artifact in artifacts:
        assert artifact.metadata is not None
        assert artifact.metadata["source"] == "sandbox_artifact_boundary"
        assert artifact.metadata["hpc_workspace_id"] == workspace["hpc_workspace_id"]
        assert artifact.metadata["fetch_ref_id"].startswith("fetch_")
        assert artifact.metadata["content_digest"].startswith("sha256:")


def test_pipeline_fpocket_missing_declared_output_fails_closed_without_synthetic_artifact() -> (
    None
):
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = MissingAllDeclaredOutputsRunner()
    sandbox = HandlerSandboxRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_fpocket_missing_output",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_fpocket_missing_output",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_fpocket_missing_output",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "declared_output_missing"
    assert error["stage"] == "hpc_output_validation"
    assert error["details"]["missing_outputs"] == ["target_out"]
    assert (
        repositories.artifacts.list_by_invocation(
            "sess_001", "inv_pipeline_fpocket_missing_output"
        )
        == []
    )
    assert not any(
        bool((artifact.metadata or {}).get("synthetic_source"))
        for artifact in repositories.artifacts.list_by_session("sess_001")
    )


def test_pipeline_explicit_non_cutover_fixture_marks_placeholder_ineligible() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = ExplicitNonCutoverFixtureRunner()
    engine = ExecutionEngine(
        repositories, runner, sandbox_runner=HandlerSandboxRunner()
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_fpocket_fixture_placeholder",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_fpocket_fixture_placeholder",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)
    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_fpocket_fixture_placeholder",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    synthetic = [
        artifact
        for artifact in result.artifacts
        if bool((artifact.metadata or {}).get("synthetic_source"))
    ]
    assert len(synthetic) == 1
    assert synthetic[0].metadata is not None
    assert synthetic[0].metadata["cutover_eligible"] is False
    assert synthetic[0].metadata["scientific_status"] == "fixture_non_cutover"


def test_pipeline_rejects_toy_pdb_before_fpocket_approval() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    toy_content = "ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n"
    Path("/tmp/toy_structure.pdb").write_text(toy_content, encoding="utf-8")
    artifact = repositories.artifacts.get("art_001")
    assert artifact is not None
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id=artifact.artifact_id,
            session_id=artifact.session_id,
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
            invocation_id=artifact.invocation_id,
            run_id=artifact.run_id,
            kind=artifact.kind,
            storage_uri="/tmp/toy_structure.pdb",
            relative_path="toy_structure.pdb",
            title="toy_structure.pdb",
            description=artifact.description,
            metadata={
                "source": "toy",
                "format": "pdb",
                "content_digest": _content_digest(toy_content),
            },
            created_at=artifact.created_at,
        )
    )
    runner = CapturingSuccessRunner()
    engine = ExecutionEngine(
        repositories, runner, sandbox_runner=HandlerSandboxRunner()
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_invalid_fpocket",
        _fpocket_pipeline_code(),
    )

    result = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_invalid_fpocket",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.approval is None
    assert runner.payloads == []
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "invalid_fpocket_input"
    assert error["stage"] == "input_validation"


def test_pipeline_hpc_operation_waits_for_approval_then_resumes_once() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    sandbox = HandlerSandboxRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_approval",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_approval",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )

    assert first.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert first.approval is not None
    assert runner.payloads == []

    approval = repositories.approvals.get(first.approval.approval_id)
    assert approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    resumed = engine.continue_after_approval(
        invocation_id="inv_pipeline_approval", resolution="approved"
    )
    repeated = engine.continue_after_approval(
        invocation_id="inv_pipeline_approval", resolution="approved"
    )
    status = engine.get_pipeline_status(
        session_id="sess_001",
        invocation_id="inv_pipeline_approval",
    )

    assert resumed.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert repeated.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert resumed.run is not None
    assert resumed.run.summary == "Pipeline sandbox completed."
    assert resumed.parsed_result is not None
    assert (
        resumed.parsed_result.result_summary
        == "fpocket found 2 pocket(s); top pocket score 0.928."
    )
    assert (
        status["parsed_result"]["result_summary"]
        == "fpocket found 2 pocket(s); top pocket score 0.928."
    )
    assert status["details"]["source_code_artifact_id"] == code_artifact_id
    assert status["output_artifact_ids"]
    assert status["runs"]
    assert status["artifacts"]
    provenance_artifact = next(
        artifact
        for artifact in resumed.artifacts
        if artifact.metadata
        and artifact.metadata.get("source_code_artifact_id") == code_artifact_id
    )
    assert provenance_artifact.metadata is not None
    assert provenance_artifact.metadata["source_code_digest"]
    assert provenance_artifact.metadata["source_code_version"] == 1
    assert (
        provenance_artifact.metadata["sandbox_runtime_identity_digest"]
        == (_test_sandbox_runtime_identity()["runtime_identity_digest"])
    )
    assert (
        provenance_artifact.metadata["sandbox_image_digest"]
        == (_test_sandbox_runtime_identity()["image_digest"])
    )
    assert (
        provenance_artifact.metadata["pipeline_sdk_digest"]
        == (_test_sandbox_runtime_identity()["pipeline_sdk_digest"])
    )
    public_status = str(status)
    assert "storage_uri" not in public_status
    assert "local_path" not in public_status
    assert "source_storage_uri" not in public_status
    assert "intermediate_storage_uri" not in public_status
    assert "storage_uri" not in str(resumed.parsed_result.structured_findings)
    assert len(runner.payloads) == 1
    runtime_metadata = dict(dict(runner.payloads[0]["runspec"])["metadata"])
    assert (
        runtime_metadata["sandbox_runtime_identity_digest"]
        == _test_sandbox_runtime_identity()["runtime_identity_digest"]
    )
    assert (
        runtime_metadata["sandbox_image_digest"]
        == _test_sandbox_runtime_identity()["image_digest"]
    )
    assert (
        runtime_metadata["pipeline_sdk_digest"]
        == _test_sandbox_runtime_identity()["pipeline_sdk_digest"]
    )
    assert sandbox.calls == 1


def test_pipeline_hpc_backend_failure_exposes_runner_details(tmp_path: Path) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingFailedRunner()
    sandbox = FailedHpcSandboxRunner(tmp_path / "stderr.log")
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_failed",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_failed",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=first.approval.approval_id,
            session_id=first.approval.session_id,
            task_id=first.approval.task_id,
            lane_id=first.approval.lane_id,
            kind=first.approval.kind,
            requested_action=first.approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=first.approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=first.approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    resumed = engine.continue_after_approval(
        invocation_id="inv_pipeline_hpc_failed", resolution="approved"
    )
    status = engine.get_pipeline_status(
        session_id="sess_001",
        invocation_id="inv_pipeline_hpc_failed",
    )
    error = status["output_payload"]["pipeline"]["error"]

    assert resumed.invocation.status is EngineInvocationStatus.FAILED
    assert error["type"] == "hpc_operation_failed"
    assert error["hpc_failure"]["runner_run_id"] == "runner_failed_001"
    assert error["hpc_failure"]["error_code"] == "APPTAINER_MISSING"
    assert "stderr_excerpt" not in error["hpc_failure"]
    assert "stdout_excerpt" not in error["hpc_failure"]
    assert "logs" not in error["hpc_failure"]
    assert "apptainer: command not found" not in str(status)
    assert repositories.artifacts.list_by_invocation(
        "sess_001",
        "inv_pipeline_hpc_failed",
    ) == []
    assert "partial-result.fasta" not in str(status)


def test_pipeline_hpc_staging_failure_projects_only_closed_runner_diagnostic() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        RaisingTypedStagingRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_staging_failure",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_staging_failure",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)

    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_hpc_staging_failure",
        resolution="approved",
    )

    assert result.invocation.status is EngineInvocationStatus.FAILED
    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "hpc_staging_failed"
    assert error["stage"] == "hpc_staging"
    assert error["details"] == {
        "runner_failure": {
            "schema_id": "runner_failure@1",
            "phase": "input_transfer",
            "run_id": "opaque_runner_123",
            "input_ordinal": 2,
            "content_digest": "sha256:" + "a" * 64,
            "returncode": 124,
            "timed_out": True,
            "elapsed_seconds": 120.125,
        }
    }
    public_payload = json.dumps(error, sort_keys=True)
    for forbidden in (
        "command",
        "ssh_target",
        "local_path",
        "remote_path",
        "remote_dir",
        "stderr",
        "locator",
        "credential",
    ):
        assert forbidden not in public_payload


def test_pipeline_rejects_open_runner_diagnostic_with_fixed_safe_reason() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        RaisingMalformedStagingRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_malformed_hpc_staging_failure",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_malformed_hpc_staging_failure",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)

    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_malformed_hpc_staging_failure",
        resolution="approved",
    )

    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["type"] == "hpc_staging_failed"
    assert error["details"] == {
        "reason": "HPC runner returned an invalid staging diagnostic.",
    }
    public_payload = json.dumps(error, sort_keys=True)
    for private_value in (
        "remote_path",
        "/private/runner/input.fasta",
        "alice@private-hpc",
        "~/secret",
        "credential",
        "must-not-cross",
    ):
        assert private_value not in public_payload


def test_pipeline_throwing_runner_projector_uses_fixed_safe_reason() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = ExecutionEngine(
        repositories,
        RaisingThrowingStagingRunner(),
        sandbox_runner=HandlerSandboxRunner(),
    )
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_throwing_hpc_staging_failure",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_throwing_hpc_staging_failure",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    _approve_request(repositories, first.approval)

    result = engine.continue_after_approval(
        invocation_id="inv_pipeline_throwing_hpc_staging_failure",
        resolution="approved",
    )

    assert result.parsed_result is not None
    error = result.parsed_result.structured_findings["error"]
    assert error["details"] == {
        "reason": "HPC runner returned an invalid staging diagnostic.",
    }
    public_payload = json.dumps(error, sort_keys=True)
    for private_value in (
        "alice@private-hpc",
        "~/secret",
        "credential",
        "must-not-cross",
        "/home/alice",
    ):
        assert private_value not in public_payload


def test_runner_projector_absence_remains_distinct_from_invalid_projection() -> None:
    from openzyme_engines.execution import _legacy_runner_failure_reason
    from openzyme_engines.execution import _project_runner_staging_failure

    legacy = RuntimeError("runner failed at /home/alice/private/input.fasta")
    invalid = RuntimeError("alice@private-hpc:~/secret credential=must-not-cross")
    invalid.to_safe_diagnostic = None  # type: ignore[attr-defined]

    assert _project_runner_staging_failure(legacy) == (False, None)
    assert _project_runner_staging_failure(invalid) == (True, None)
    assert _legacy_runner_failure_reason(legacy) == (
        "runner failed at [redacted-path]"
    )


def test_engine_accepts_closed_runner_control_transfer_projection() -> None:
    from mcp_hpc_runner.errors import HpcStagingFailure
    from openzyme_engines.execution import _project_runner_staging_failure

    failure = HpcStagingFailure(
        phase="runner_control_transfer",
        run_id="opaque_control_123",
        input_ordinal=None,
        content_digest="sha256:" + "c" * 64,
        returncode=1,
        timed_out=False,
        elapsed_seconds=0.25,
    )

    assert _project_runner_staging_failure(failure) == (
        True,
        failure.to_safe_diagnostic(),
    )


def test_pipeline_hpc_runner_timeout_is_not_sandbox_preflight_failure(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingTimeoutRunner()
    sandbox = FailedHpcSandboxRunner(tmp_path / "stderr.log")
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_hpc_timeout",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_hpc_timeout",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=first.approval.approval_id,
            session_id=first.approval.session_id,
            task_id=first.approval.task_id,
            lane_id=first.approval.lane_id,
            kind=first.approval.kind,
            requested_action=first.approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=first.approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=first.approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    engine.continue_after_approval(
        invocation_id="inv_pipeline_hpc_timeout", resolution="approved"
    )
    status = engine.get_pipeline_status(
        session_id="sess_001",
        invocation_id="inv_pipeline_hpc_timeout",
    )
    error = status["output_payload"]["pipeline"]["error"]

    assert error["type"] == "hpc_runner_timeout"
    assert error["stage"] == "remote_execution"
    assert error["hpc_failure"]["error_code"] == "COMMAND_TIMEOUT"


def test_pipeline_runtime_unplanned_hpc_operation_requests_secondary_approval() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    runner = CapturingSuccessRunner()
    sandbox = UnplannedHpcSandboxRunner()
    engine = ExecutionEngine(repositories, runner, sandbox_runner=sandbox)
    code_artifact_id = _pipeline_source_id(
        repositories,
        "code_unplanned_hpc",
        _fpocket_pipeline_code(),
    )

    first = engine.start_pipeline(
        session_id="sess_001",
        task_id="task_001",
        invocation_id="inv_pipeline_unplanned",
        code_artifact_id=code_artifact_id,
        inputs={"artifact_ids": ["art_001"]},
    )
    assert first.approval is not None
    repositories.approvals.save(
        ApprovalRequest(
            approval_id=first.approval.approval_id,
            session_id=first.approval.session_id,
            task_id=first.approval.task_id,
            lane_id=first.approval.lane_id,
            kind=first.approval.kind,
            requested_action=first.approval.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=first.approval.request_ref,
            resolution_ref="artifact://approval-resolution.json",
            created_at=first.approval.created_at,
            resolved_at="2026-04-20T12:10:00+00:00",
        )
    )

    resumed = engine.continue_after_approval(
        invocation_id="inv_pipeline_unplanned", resolution="approved"
    )

    assert resumed.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
    assert resumed.approval is not None
    assert resumed.approval.kind == "execution_pipeline_operation"
    assert runner.payloads == []
