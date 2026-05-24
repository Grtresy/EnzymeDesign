from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import tempfile
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_core import EngineDescriptor
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import ToolResult
from openzyme_core.artifact_projection import project_artifact_for_agent
from openzyme_core.artifact_projection import sanitize_private_artifact_fields
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import RunRecord
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain.control_plane import utc_now_iso
from openzyme_tools import get_hpc_tool_contract
from openzyme_tools.contracts import ToolExecutionContract


def _new_document_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _safe_ref(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "artifact"


def _invocation_status_from_run(run_status: RunStatus) -> EngineInvocationStatus:
    return {
        RunStatus.QUEUED: EngineInvocationStatus.RUNNING,
        RunStatus.RUNNING: EngineInvocationStatus.RUNNING,
        RunStatus.SUCCEEDED: EngineInvocationStatus.SUCCEEDED,
        RunStatus.FAILED: EngineInvocationStatus.FAILED,
        RunStatus.CANCELLED: EngineInvocationStatus.CANCELLED,
    }[run_status]


def _artifact_kind_from_path(path: str) -> ArtifactKind:
    lowered = path.lower()
    if lowered.endswith(".log") or "/logs/" in lowered:
        return ArtifactKind.LOG
    if lowered.endswith((".pdb", ".cif", ".mol2", ".sdf", ".pdbqt")):
        return ArtifactKind.STRUCTURE
    if lowered.endswith((".md", ".pdf", ".html")):
        return ArtifactKind.REPORT
    return ArtifactKind.RESULT


def _runner_relative_path(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized.startswith("/"):
        raise ValueError(f"runner path must be relative: {value!r}")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"runner path must not contain empty, '.', or '..' segments: {value!r}")
    if any(char in normalized for char in (";", "&", "|", "`", "$", "\\", "\n", "\r")):
        raise ValueError(f"runner path must not contain shell metacharacters: {value!r}")
    return normalized


def _number_arg(value: Any, default: float | int) -> str:
    candidate = default if value is None else value
    try:
        number = float(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"numeric execution parameter must be a number: {candidate!r}") from exc
    if number.is_integer():
        return str(int(number))
    return str(number)


def _text_excerpt(path: str, *, limit: int = 2000) -> str | None:
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not content:
        return None
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "\n...[truncated]"


def _inline_excerpt(value: Any, *, limit: int = 2000) -> str | None:
    if value is None:
        return None
    content = str(value).strip()
    if not content:
        return None
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "\n...[truncated]"


def _count_pdb_atoms_and_residues(path: str) -> tuple[int, int]:
    atom_count = 0
    residues: set[tuple[str, str, str]] = set()
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, 0
    for line in lines:
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_count += 1
        chain_id = line[21:22].strip() if len(line) >= 22 else ""
        residue_id = line[22:26].strip() if len(line) >= 26 else str(atom_count)
        insertion_code = line[26:27].strip() if len(line) >= 27 else ""
        residues.add((chain_id, residue_id, insertion_code))
    return atom_count, len(residues)


def _hpc_failure_details(result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("status") != RunStatus.FAILED.value:
        return None
    raw = result.get("runner_result")
    if not isinstance(raw, dict):
        raw = {}
    details: dict[str, Any] = {
        "run_id": result.get("run_id"),
        "runner_run_id": result.get("runner_run_id"),
        "status": result.get("status"),
        "execution_mode": result.get("execution_mode"),
        "exit_code": result.get("exit_code"),
        "error_code": raw.get("error_code"),
        "stage": raw.get("stage") or result.get("stage"),
        "stdout_excerpt": _inline_excerpt(raw.get("stdout")),
        "stderr_excerpt": _inline_excerpt(raw.get("stderr")),
    }
    logs = raw.get("logs")
    if isinstance(logs, dict):
        inline_logs: dict[str, Any] = {}
        for key in ("stdout", "stderr"):
            value = logs.get(key)
            if isinstance(value, dict):
                inline_logs[key] = {
                    item_key: item_value
                    for item_key, item_value in value.items()
                    if item_key in {"text", "truncated", "line_count"}
                }
        if inline_logs:
            details["logs"] = inline_logs
    return {key: value for key, value in details.items() if value is not None}


def _render_contract_command(contract: ToolExecutionContract, tool_inputs: dict[str, Any]) -> list[str]:
    if contract.command_template_id == "fpocket_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'apptainer exec --cleanenv --pwd /out '
                '--bind "$MCP_WORKDIR:/work" --bind "$MCP_OUTDIR:/out" '
                '--bind "$MCP_TMPDIR:/tmp" ~/containers/fpocket.sif fpocket -f /work/target.pdb && '
                'if [ -d "$MCP_WORKDIR/target_out" ]; then rm -rf "$MCP_OUTDIR/target_out" && '
                'mv "$MCP_WORKDIR/target_out" "$MCP_OUTDIR/target_out"; fi'
            ),
        ]
    if contract.command_template_id == "vina_sif_v1":
        return [
            "bash",
            "-lc",
            (
                'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
                '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" ~/containers/vina.sif vina '
                "--receptor /work/receptor.pdbqt --ligand /work/ligand.pdbqt "
                f"--center_x {_number_arg(tool_inputs.get('center_x'), 0)} "
                f"--center_y {_number_arg(tool_inputs.get('center_y'), 0)} "
                f"--center_z {_number_arg(tool_inputs.get('center_z'), 0)} "
                f"--size_x {_number_arg(tool_inputs.get('size_x'), 10)} "
                f"--size_y {_number_arg(tool_inputs.get('size_y'), 10)} "
                f"--size_z {_number_arg(tool_inputs.get('size_z'), 10)} "
                f"--exhaustiveness {_number_arg(tool_inputs.get('exhaustiveness'), 8)} "
                f"--num_modes {_number_arg(tool_inputs.get('num_modes'), 9)} "
                "--out /out/vina_out.pdbqt --log /out/vina.log"
            ),
        ]
    raise ValueError(f"unsupported command template {contract.command_template_id!r}")


def _contract_payload(contract: ToolExecutionContract) -> dict[str, Any]:
    return {
        "adapter_id": contract.adapter_id,
        "tool_id": contract.tool_id,
        "command_template_id": contract.command_template_id,
        "parser_hints": contract.parser_hints,
        "preprocess_requirements": contract.preprocess_requirements,
    }


def _contract_outputs(contract: ToolExecutionContract) -> list[dict[str, Any]]:
    return [
        {
            "path": _runner_relative_path(output.path),
            "kind": output.kind,
            "required": output.required,
            "non_empty": output.non_empty,
        }
        for output in contract.expected_outputs
    ]


@dataclass(frozen=True, slots=True)
class ExecutionArtifactRef:
    storage_uri: str
    relative_path: str
    kind: ArtifactKind

    def to_dict(self) -> dict[str, Any]:
        return {
            "storage_uri": self.storage_uri,
            "relative_path": self.relative_path,
            "kind": self.kind.value,
        }


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: RunStatus
    execution_mode: str
    remote_run_dir: str
    raw_result: dict[str, Any]
    artifacts: tuple[ExecutionArtifactRef, ...] = ()
    job_id: str | None = None
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusSnapshot:
    run_id: str
    status: RunStatus
    remote_run_dir: str
    raw_result: dict[str, Any]
    job_id: str | None = None
    exit_code: int | None = None


class ExecutionRunner(Protocol):
    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> ExecutionOutcome: ...

    def get_execution_status(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> ExecutionStatusSnapshot: ...

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        runspec: dict[str, Any],
        job_id: str | None = None,
    ) -> ExecutionOutcome: ...

    def cancel_execution(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> ExecutionOutcome: ...


@dataclass(frozen=True, slots=True)
class ExecutionParsedResult:
    result_summary: str
    structured_findings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_summary": self.result_summary,
            "structured_findings": self.structured_findings,
        }


class ExecutionRequestCompiler(Protocol):
    def compile_request(
        self,
        *,
        handoff: "ExecutionHandoff",
        task: Any,
        resolved_required_artifacts: tuple[SessionArtifactRecord, ...],
        resolved_context_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> dict[str, Any]: ...


class ExecutionResultParser(Protocol):
    def parse_result(
        self,
        *,
        handoff: "ExecutionHandoff",
        outcome: ExecutionOutcome,
        artifact_refs: tuple[SessionArtifactRecord, ...],
    ) -> ExecutionParsedResult: ...


class PipelineApprovalRequired(RuntimeError):
    def __init__(self, approval: ApprovalRequest) -> None:
        super().__init__(f"pipeline operation requires approval: {approval.approval_id}")
        self.approval = approval


class PipelineSdkFailure(RuntimeError):
    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        hint: str,
        stage: str,
        retryable: bool,
        sdk_method: str | None = None,
        hpc_failure: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.hint = hint
        self.stage = stage
        self.retryable = retryable
        self.sdk_method = sdk_method
        self.hpc_failure = hpc_failure
        self.details = {} if details is None else dict(details)


class PipelineSourceError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        hint: str,
        stage: str = "source_code_artifact_validation",
        retryable: bool = False,
        source_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.hint = hint
        self.stage = stage
        self.retryable = retryable
        self.source_metadata = {} if source_metadata is None else dict(source_metadata)


@dataclass(frozen=True, slots=True)
class PipelineSource:
    artifact: SessionArtifactRecord
    code: str
    code_digest: str
    source_code_digest: str
    source_code_version: int | None

    def metadata(self) -> dict[str, Any]:
        return {
            "source_code_artifact_id": self.artifact.artifact_id,
            "source_code_digest": self.source_code_digest,
            "source_code_version": self.source_code_version,
        }


@dataclass(frozen=True, slots=True)
class BioArtifactDraft:
    relative_path: str
    kind: ArtifactKind
    title: str
    content: str
    format: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BioSdkResult:
    provider: str
    operation: str
    summary: dict[str, Any]
    artifacts: tuple[BioArtifactDraft, ...]
    warnings: tuple[dict[str, Any], ...] = ()


class BioDatabaseAdapter(Protocol):
    def ncbi_fetch_proteins(
        self,
        *,
        accessions: tuple[str, ...],
        fields: tuple[str, ...],
        retrieved_at: str,
    ) -> BioSdkResult: ...

    def uniprot_fetch(
        self,
        *,
        accessions: tuple[str, ...],
        fields: tuple[str, ...],
        batch_size: int | None,
        retrieved_at: str,
    ) -> BioSdkResult: ...

    def hmmer_search(
        self,
        *,
        hmm_artifact: SessionArtifactRecord,
        database: str,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult: ...


class DeterministicBioDatabaseAdapter:
    tool_version = "openzyme-fixture-bio-v1"

    def ncbi_fetch_proteins(
        self,
        *,
        accessions: tuple[str, ...],
        fields: tuple[str, ...],
        retrieved_at: str,
    ) -> BioSdkResult:
        accessions, warnings = self._normalize_accessions(
            accessions,
            provider="ncbi",
            sdk_method="bio.ncbi_fetch_proteins",
        )
        records = [self._protein_record(accession, provider="ncbi", reviewed=None) for accession in accessions]
        metadata_records = [self._metadata_record(record) for record in records]
        fasta = self._fasta(records)
        metadata_payload = {
            "provider": "ncbi",
            "database": "protein",
            "fields": list(fields),
            "records": metadata_records,
            "warnings": list(warnings),
            "retrieved_at": retrieved_at,
            "tool_version": self.tool_version,
            "api_version": "fixture",
        }
        summary = {
            "provider": "ncbi",
            "database": "protein",
            "accession_count": len(accessions),
            "record_count": len(records),
            "warning_count": len(warnings),
            "request_window": {"start": 0, "size": len(accessions)},
        }
        return BioSdkResult(
            provider="ncbi",
            operation="bio.ncbi_fetch_proteins",
            summary=summary,
            warnings=warnings,
            artifacts=(
                self._draft(
                    provider="ncbi",
                    relative_path="bio/ncbi/proteins.fasta",
                    kind=ArtifactKind.SEQUENCE,
                    title="ncbi_proteins.fasta",
                    content=fasta,
                    format="fasta",
                    metadata={
                        "database": "protein",
                        "accessions": list(accessions),
                        "retrieved_at": retrieved_at,
                    },
                ),
                self._draft(
                    provider="ncbi",
                    relative_path="bio/ncbi/proteins.metadata.json",
                    kind=ArtifactKind.RESULT,
                    title="ncbi_proteins.metadata.json",
                    content=json.dumps(metadata_payload, sort_keys=True, indent=2) + "\n",
                    format="json",
                    metadata={
                        "database": "protein",
                        "accessions": list(accessions),
                        "retrieved_at": retrieved_at,
                    },
                ),
            ),
        )

    def uniprot_fetch(
        self,
        *,
        accessions: tuple[str, ...],
        fields: tuple[str, ...],
        batch_size: int | None,
        retrieved_at: str,
    ) -> BioSdkResult:
        accessions, warnings = self._normalize_accessions(
            accessions,
            provider="uniprot",
            sdk_method="bio.uniprot_fetch",
        )
        if batch_size is not None and batch_size <= 0:
            raise PipelineSdkFailure(
                error_type="invalid_batch_size",
                message="bio.uniprot_fetch batch_size must be positive.",
                hint="Retry with batch_size omitted or set to a positive integer.",
                stage="bio_input_validation",
                retryable=False,
                sdk_method="bio.uniprot_fetch",
                details={"batch_size": batch_size},
            )
        effective_batch_size = batch_size or min(max(len(accessions), 1), 100)
        records = [self._protein_record(accession, provider="uniprot", reviewed=True) for accession in accessions]
        metadata_records = [self._metadata_record(record) for record in records]
        metadata_payload = {
            "provider": "uniprot",
            "database": "uniprotkb",
            "fields": list(fields),
            "batch_size": effective_batch_size,
            "records": metadata_records,
            "warnings": list(warnings),
            "retrieved_at": retrieved_at,
            "tool_version": self.tool_version,
            "api_version": "fixture",
        }
        summary = {
            "provider": "uniprot",
            "database": "uniprotkb",
            "accession_count": len(accessions),
            "record_count": len(records),
            "warning_count": len(warnings),
            "request_window": {"start": 0, "size": effective_batch_size},
            "pagination": {"page_count": max(1, (len(accessions) + effective_batch_size - 1) // effective_batch_size)},
        }
        return BioSdkResult(
            provider="uniprot",
            operation="bio.uniprot_fetch",
            summary=summary,
            warnings=warnings,
            artifacts=(
                self._draft(
                    provider="uniprot",
                    relative_path="bio/uniprot/sequences.fasta",
                    kind=ArtifactKind.SEQUENCE,
                    title="uniprot_sequences.fasta",
                    content=self._fasta(records),
                    format="fasta",
                    metadata={
                        "database": "uniprotkb",
                        "accessions": list(accessions),
                        "retrieved_at": retrieved_at,
                        "request_window": {"start": 0, "size": effective_batch_size},
                    },
                ),
                self._draft(
                    provider="uniprot",
                    relative_path="bio/uniprot/metadata.json",
                    kind=ArtifactKind.RESULT,
                    title="uniprot_metadata.json",
                    content=json.dumps(metadata_payload, sort_keys=True, indent=2) + "\n",
                    format="json",
                    metadata={
                        "database": "uniprotkb",
                        "accessions": list(accessions),
                        "retrieved_at": retrieved_at,
                        "request_window": {"start": 0, "size": effective_batch_size},
                    },
                ),
            ),
        )

    def hmmer_search(
        self,
        *,
        hmm_artifact: SessionArtifactRecord,
        database: str,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult:
        normalized_database = database.strip().lower()
        if not normalized_database:
            raise PipelineSdkFailure(
                error_type="missing_hmmer_database",
                message="bio.hmmer_search requires a database.",
                hint="Pass a target database name such as uniprotkb or reference_proteomes.",
                stage="bio_input_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
            )
        if params.get("simulate") == "timeout":
            raise PipelineSdkFailure(
                error_type="bio_provider_timeout",
                message="EBI HMMER request timed out before completion.",
                hint="Retry with a smaller database or wait for provider recovery.",
                stage="bio_provider_request",
                retryable=True,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", "database": normalized_database},
            )
        if params.get("simulate") == "schema_drift":
            raise PipelineSdkFailure(
                error_type="bio_schema_drift",
                message="EBI HMMER response schema did not match the expected hits shape.",
                hint="Inspect provider response compatibility before treating this as an empty hit set.",
                stage="bio_result_parse",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", "database": normalized_database},
            )
        if params.get("simulate") == "pagination_failure":
            raise PipelineSdkFailure(
                error_type="bio_pagination_failure",
                message="EBI HMMER pagination failed before all pages were retrieved.",
                hint="Retry the request or reduce the search scope; do not treat partial pages as complete.",
                stage="bio_provider_pagination",
                retryable=True,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", "database": normalized_database, "cursor": "fixture-page-2"},
            )
        hit_count = 0 if normalized_database == "empty" else 1
        warnings: tuple[dict[str, Any], ...] = ()
        if hit_count == 0:
            warnings = (
                {
                    "warning_code": "empty_results",
                    "stage": "bio_result_parse",
                    "hint": "The HMMER provider returned no hits for this query/database.",
                    "affected_range": {"start": 0, "end": 0},
                },
            )
        raw_payload = {
            "provider": "ebi_hmmer",
            "database": normalized_database,
            "query_hmm_artifact_id": hmm_artifact.artifact_id,
            "params": params,
            "hits": []
            if hit_count == 0
            else [
                {
                    "target": "fixture_hit_001",
                    "accession": "FIXTURE001",
                    "evalue": 1e-42,
                    "score": 187.2,
                }
            ],
            "retrieved_at": retrieved_at,
            "tool_version": self.tool_version,
            "api_version": "fixture",
        }
        parsed_csv = "target,accession,evalue,score\n"
        if hit_count:
            parsed_csv += "fixture_hit_001,FIXTURE001,1e-42,187.2\n"
        summary = {
            "provider": "ebi_hmmer",
            "database": normalized_database,
            "query_hmm_artifact_id": hmm_artifact.artifact_id,
            "hit_count": hit_count,
            "warning_count": len(warnings),
            "request_window": {"start": 0, "size": hit_count},
            "pagination": {"page_count": 1, "cursor": None},
        }
        return BioSdkResult(
            provider="ebi_hmmer",
            operation="bio.hmmer_search",
            summary=summary,
            warnings=warnings,
            artifacts=(
                self._draft(
                    provider="ebi_hmmer",
                    relative_path="bio/hmmer/raw_hits.json",
                    kind=ArtifactKind.RESULT,
                    title="hmmer_raw_hits.json",
                    content=json.dumps(raw_payload, sort_keys=True, indent=2) + "\n",
                    format="json",
                    metadata={
                        "database": normalized_database,
                        "query_hmm_artifact_id": hmm_artifact.artifact_id,
                        "retrieved_at": retrieved_at,
                    },
                ),
                self._draft(
                    provider="ebi_hmmer",
                    relative_path="bio/hmmer/parsed_hits.csv",
                    kind=ArtifactKind.RESULT,
                    title="hmmer_parsed_hits.csv",
                    content=parsed_csv,
                    format="csv",
                    metadata={
                        "database": normalized_database,
                        "query_hmm_artifact_id": hmm_artifact.artifact_id,
                        "retrieved_at": retrieved_at,
                    },
                ),
            ),
        )

    def _normalize_accessions(
        self,
        accessions: tuple[str, ...],
        *,
        provider: str,
        sdk_method: str,
    ) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
        if not accessions:
            raise PipelineSdkFailure(
                error_type="missing_accessions",
                message=f"bio {provider} fetch requires at least one accession.",
                hint="Pass one or more accession strings.",
                stage="bio_input_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        if len(accessions) > 100:
            raise PipelineSdkFailure(
                error_type="bio_quota_exceeded",
                message="Bio SDK fixture batch size is capped at 100 accessions per operation.",
                hint="Split the request into smaller batches.",
                stage="bio_quota_check",
                retryable=False,
                sdk_method=sdk_method,
                details={"accession_count": len(accessions), "limit": 100},
            )
        normalized: list[str] = []
        warnings: list[dict[str, Any]] = []
        for index, accession in enumerate(accessions):
            value = accession.strip()
            if not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                raise PipelineSdkFailure(
                    error_type="invalid_accession",
                    message=f"Invalid accession at index {index}: {accession!r}.",
                    hint="Use provider accession identifiers without whitespace or punctuation.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"accession": accession, "index": index},
                )
            if value.upper().startswith("MISSING"):
                warnings.append(
                    {
                        "warning_code": "partial_accession_missing",
                        "stage": "bio_provider_response",
                        "hint": "Provider did not return this accession; remaining records were artifactized.",
                        "accession": value,
                        "affected_range": {"start": index, "end": index + 1},
                    }
                )
                continue
            normalized.append(value)
        if not normalized:
            warnings.append(
                {
                    "warning_code": "empty_results",
                    "stage": "bio_provider_response",
                    "hint": "No requested accessions returned records.",
                    "affected_range": {"start": 0, "end": len(accessions)},
                }
            )
        return tuple(normalized), tuple(warnings)

    def _protein_record(self, accession: str, *, provider: str, reviewed: bool | None) -> dict[str, Any]:
        sequence = self._sequence_for(accession)
        record = {
            "accession": accession,
            "description": f"{provider} fixture protein {accession}",
            "length": len(sequence),
            "taxonomy": "synthetic fixture",
            "sequence": sequence,
        }
        if reviewed is not None:
            record["reviewed"] = reviewed
        return record

    def _metadata_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "sequence"}

    def _sequence_for(self, accession: str) -> str:
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        seed = sum(ord(char) for char in accession)
        return "M" + "".join(alphabet[(seed + index) % len(alphabet)] for index in range(59))

    def _fasta(self, records: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for record in records:
            lines.append(f">{record['accession']} {record['description']}")
            lines.append(str(record["sequence"]))
        return "\n".join(lines) + ("\n" if lines else "")

    def _draft(
        self,
        *,
        provider: str,
        relative_path: str,
        kind: ArtifactKind,
        title: str,
        content: str,
        format: str,
        metadata: dict[str, Any],
    ) -> BioArtifactDraft:
        response_digest = f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        return BioArtifactDraft(
            relative_path=relative_path,
            kind=kind,
            title=title,
            content=content,
            format=format,
            metadata={
                "source": "host_supervised_bio_sdk",
                "provider": provider,
                "format": format,
                "response_digest": response_digest,
                "tool_version": self.tool_version,
                "api_version": "fixture",
                **metadata,
            },
        )


class BioToolsAdapter(Protocol):
    def cdhit(
        self,
        *,
        input_fasta: SessionArtifactRecord,
        identity: float,
        mode: str,
        retrieved_at: str,
    ) -> BioSdkResult: ...

    def mafft(
        self,
        *,
        input_fasta: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult: ...

    def hmmbuild(
        self,
        *,
        alignment: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult: ...

    def hmmalign(
        self,
        *,
        hmm: SessionArtifactRecord,
        fasta: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult: ...

    def hmmer_search_cli(
        self,
        *,
        hmm: SessionArtifactRecord,
        target_fasta: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult: ...


class DeterministicBioToolsAdapter:
    tool_version = "openzyme-fixture-bio-tools-v1"

    def cdhit(
        self,
        *,
        input_fasta: SessionArtifactRecord,
        identity: float,
        mode: str,
        retrieved_at: str,
    ) -> BioSdkResult:
        self._ensure_tool_available("bio_tools.cdhit", params={"mode": mode})
        if identity <= 0 or identity > 1:
            raise self._failure(
                "bio_tools.cdhit",
                "invalid_tool_parameter",
                "cd-hit identity must be in the range (0, 1].",
                "Retry with an identity threshold such as 0.9.",
                "bio_tools_input_validation",
                details={"identity": identity},
            )
        sequences = self._read_fasta(input_fasta, sdk_method="bio_tools.cdhit")
        content = self._fasta(sequences[: max(1, len(sequences))])
        summary = {
            "tool_name": "cd-hit",
            "input_artifact_ids": [input_fasta.artifact_id],
            "sequence_count": len(sequences),
            "cluster_count": len(sequences),
            "identity": identity,
            "mode": mode,
        }
        return self._result(
            operation="bio_tools.cdhit",
            summary=summary,
            artifacts=(
                self._draft(
                    relative_path="bio_tools/cdhit/clustered.fasta",
                    kind=ArtifactKind.SEQUENCE,
                    title="cdhit_clustered.fasta",
                    content=content,
                    format="fasta",
                    metadata={
                        "tool_name": "cd-hit",
                        "input_artifact_ids": [input_fasta.artifact_id],
                        "parameters": {"identity": identity, "mode": mode},
                        "retrieved_at": retrieved_at,
                    },
                    required_format="fasta",
                ),
                self._draft(
                    relative_path="bio_tools/cdhit/clusters.csv",
                    kind=ArtifactKind.RESULT,
                    title="cdhit_clusters.csv",
                    content="cluster_id,representative,member_count\ncluster_1," + sequences[0][0] + f",{len(sequences)}\n",
                    format="csv",
                    metadata={
                        "tool_name": "cd-hit",
                        "input_artifact_ids": [input_fasta.artifact_id],
                        "parameters": {"identity": identity, "mode": mode},
                        "retrieved_at": retrieved_at,
                    },
                    required_format="csv",
                    required_columns=("cluster_id", "representative", "member_count"),
                ),
            ),
        )

    def mafft(
        self,
        *,
        input_fasta: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult:
        self._ensure_tool_available("bio_tools.mafft", params=params)
        sequences = self._read_fasta(input_fasta, sdk_method="bio_tools.mafft")
        content = self._fasta([(name, sequence + "-" * (index % 2)) for index, (name, sequence) in enumerate(sequences)])
        summary = {
            "tool_name": "mafft",
            "input_artifact_ids": [input_fasta.artifact_id],
            "sequence_count": len(sequences),
            "alignment_length": max(len(sequence) for _, sequence in sequences),
        }
        return self._result(
            operation="bio_tools.mafft",
            summary=summary,
            artifacts=(
                self._draft(
                    relative_path="bio_tools/mafft/alignment.fasta",
                    kind=ArtifactKind.SEQUENCE,
                    title="mafft_alignment.fasta",
                    content=content,
                    format="fasta",
                    metadata={
                        "tool_name": "mafft",
                        "input_artifact_ids": [input_fasta.artifact_id],
                        "parameters": params,
                        "retrieved_at": retrieved_at,
                    },
                    required_format="fasta",
                ),
            ),
        )

    def hmmbuild(
        self,
        *,
        alignment: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult:
        self._ensure_tool_available("bio_tools.hmmbuild", params=params)
        sequences = self._read_fasta(alignment, sdk_method="bio_tools.hmmbuild")
        hmm = "HMMER3/f [OpenZyme fixture]\nNAME openzyme_fixture\nLENG " + str(max(len(item[1]) for item in sequences)) + "\n//\n"
        summary = {
            "tool_name": "hmmbuild",
            "input_artifact_ids": [alignment.artifact_id],
            "sequence_count": len(sequences),
        }
        return self._result(
            operation="bio_tools.hmmbuild",
            summary=summary,
            artifacts=(
                self._draft(
                    relative_path="bio_tools/hmmbuild/model.hmm",
                    kind=ArtifactKind.RESULT,
                    title="hmmbuild_model.hmm",
                    content=hmm,
                    format="hmm",
                    metadata={
                        "tool_name": "hmmbuild",
                        "input_artifact_ids": [alignment.artifact_id],
                        "parameters": params,
                        "retrieved_at": retrieved_at,
                    },
                    required_format="hmm",
                ),
            ),
        )

    def hmmalign(
        self,
        *,
        hmm: SessionArtifactRecord,
        fasta: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult:
        self._ensure_tool_available("bio_tools.hmmalign", params=params)
        self._read_hmm(hmm, sdk_method="bio_tools.hmmalign")
        sequences = self._read_fasta(fasta, sdk_method="bio_tools.hmmalign")
        content = self._fasta([(name, sequence + ".") for name, sequence in sequences])
        summary = {
            "tool_name": "hmmalign",
            "input_artifact_ids": [hmm.artifact_id, fasta.artifact_id],
            "aligned_sequence_count": len(sequences),
        }
        return self._result(
            operation="bio_tools.hmmalign",
            summary=summary,
            artifacts=(
                self._draft(
                    relative_path="bio_tools/hmmalign/aligned.fasta",
                    kind=ArtifactKind.SEQUENCE,
                    title="hmmalign_aligned.fasta",
                    content=content,
                    format="fasta",
                    metadata={
                        "tool_name": "hmmalign",
                        "input_artifact_ids": [hmm.artifact_id, fasta.artifact_id],
                        "parameters": params,
                        "retrieved_at": retrieved_at,
                    },
                    required_format="fasta",
                ),
            ),
        )

    def hmmer_search_cli(
        self,
        *,
        hmm: SessionArtifactRecord,
        target_fasta: SessionArtifactRecord,
        params: dict[str, Any],
        retrieved_at: str,
    ) -> BioSdkResult:
        self._ensure_tool_available("bio_tools.hmmer_search_cli", params=params)
        self._read_hmm(hmm, sdk_method="bio_tools.hmmer_search_cli")
        sequences = self._read_fasta(target_fasta, sdk_method="bio_tools.hmmer_search_cli")
        if params.get("simulate") == "declared_output_missing":
            raise self._failure(
                "bio_tools.hmmer_search_cli",
                "declared_output_missing",
                "Declared HMMER tblout output was not produced.",
                "Inspect tool logs and rerun with corrected inputs.",
                "bio_tools_output_validation",
                retryable=False,
            )
        if params.get("simulate") == "invalid_output":
            raise self._failure(
                "bio_tools.hmmer_search_cli",
                "invalid_hmmer_tblout",
                "Declared HMMER tblout output is missing required columns.",
                "Do not register malformed HMMER output as a successful artifact.",
                "bio_tools_output_validation",
                retryable=False,
            )
        rows = "target,accession,evalue,score\n" + "\n".join(
            f"{name},{name},1e-20,{100 + index}.0" for index, (name, _) in enumerate(sequences)
        ) + "\n"
        log = "hmmer_search_cli completed\n" + ("x" * 512 if params.get("simulate") == "oversized_log" else "")
        summary = {
            "tool_name": "hmmsearch",
            "input_artifact_ids": [hmm.artifact_id, target_fasta.artifact_id],
            "hit_count": len(sequences),
            "log_truncated": bool(params.get("simulate") == "oversized_log"),
        }
        warnings: tuple[dict[str, Any], ...] = ()
        if params.get("simulate") == "oversized_log":
            warnings = (
                {
                    "warning_code": "log_truncated",
                    "stage": "bio_tools_log_capture",
                    "hint": "Full tool log was persisted as an artifact; RPC summary is truncated.",
                    "affected_range": {"start": 0, "end": len(log)},
                },
            )
        return self._result(
            operation="bio_tools.hmmer_search_cli",
            summary=summary,
            warnings=warnings,
            artifacts=(
                self._draft(
                    relative_path="bio_tools/hmmer_search_cli/hits.csv",
                    kind=ArtifactKind.RESULT,
                    title="hmmer_hits.csv",
                    content=rows,
                    format="csv",
                    metadata={
                        "tool_name": "hmmsearch",
                        "input_artifact_ids": [hmm.artifact_id, target_fasta.artifact_id],
                        "parameters": params,
                        "retrieved_at": retrieved_at,
                    },
                    required_format="csv",
                    required_columns=("target", "accession", "evalue", "score"),
                ),
                self._draft(
                    relative_path="bio_tools/hmmer_search_cli/tool.log",
                    kind=ArtifactKind.LOG,
                    title="hmmer_search_cli.log",
                    content=log,
                    format="log",
                    metadata={
                        "tool_name": "hmmsearch",
                        "input_artifact_ids": [hmm.artifact_id, target_fasta.artifact_id],
                        "parameters": params,
                        "retrieved_at": retrieved_at,
                        "log_truncated": bool(params.get("simulate") == "oversized_log"),
                    },
                    required_format="log",
                ),
            ),
        )

    def _ensure_tool_available(self, sdk_method: str, *, params: dict[str, Any]) -> None:
        if params.get("simulate") == "tool_missing":
            raise self._failure(
                sdk_method,
                "tool_missing",
                f"Required tool for {sdk_method} is not available in the configured Host toolchain.",
                "Install/configure the requested bio tool; do not silently substitute another command.",
                "bio_tools_preflight",
                retryable=False,
            )
        if params.get("simulate") == "resource_limit_exceeded":
            raise self._failure(
                sdk_method,
                "resource_limit_exceeded",
                f"Requested resources exceed the configured local bio tool limit for {sdk_method}.",
                "Reduce input size or route through an explicitly approved HPC-backed operation.",
                "bio_tools_resource_check",
                retryable=False,
            )

    def _read_fasta(self, artifact: SessionArtifactRecord, *, sdk_method: str) -> list[tuple[str, str]]:
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if metadata_format not in {"fasta", "fa", "faa"} and not artifact.relative_path.lower().endswith((".fasta", ".fa", ".faa")):
            raise self._failure(
                sdk_method,
                "invalid_fasta",
                f"Artifact {artifact.artifact_id!r} must be a FASTA sequence artifact.",
                "Provide a FASTA artifact generated by bio.* or bio_tools.*.",
                "bio_tools_input_validation",
                details={"artifact_id": artifact.artifact_id, "format": metadata_format},
            )
        content = Path(artifact.storage_uri).read_text(encoding="utf-8")
        records: list[tuple[str, str]] = []
        current_name: str | None = None
        current_sequence: list[str] = []
        for line in content.splitlines():
            if line.startswith(">"):
                if current_name is not None:
                    records.append((current_name, "".join(current_sequence)))
                current_name = line[1:].split(maxsplit=1)[0] or f"seq{len(records) + 1}"
                current_sequence = []
            elif line.strip():
                current_sequence.append(line.strip())
        if current_name is not None:
            records.append((current_name, "".join(current_sequence)))
        if not records or any(not sequence for _, sequence in records):
            raise self._failure(
                sdk_method,
                "invalid_fasta",
                f"Artifact {artifact.artifact_id!r} is empty or not valid FASTA.",
                "Provide a non-empty FASTA with at least one sequence.",
                "bio_tools_input_validation",
                details={"artifact_id": artifact.artifact_id},
            )
        return records

    def _read_hmm(self, artifact: SessionArtifactRecord, *, sdk_method: str) -> str:
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if metadata_format != "hmm" and not artifact.relative_path.lower().endswith(".hmm"):
            raise self._failure(
                sdk_method,
                "invalid_hmm",
                f"Artifact {artifact.artifact_id!r} must be an HMM artifact.",
                "Provide an HMM artifact generated by bio_tools.hmmbuild.",
                "bio_tools_input_validation",
                details={"artifact_id": artifact.artifact_id, "format": metadata_format},
            )
        content = Path(artifact.storage_uri).read_text(encoding="utf-8")
        if not content.startswith("HMMER"):
            raise self._failure(
                sdk_method,
                "invalid_hmm",
                f"Artifact {artifact.artifact_id!r} does not look like HMMER output.",
                "Regenerate the HMM with bio_tools.hmmbuild.",
                "bio_tools_input_validation",
                details={"artifact_id": artifact.artifact_id},
            )
        return content

    def _fasta(self, records: list[tuple[str, str]]) -> str:
        return "".join(f">{name}\n{sequence}\n" for name, sequence in records)

    def _draft(
        self,
        *,
        relative_path: str,
        kind: ArtifactKind,
        title: str,
        content: str,
        format: str,
        metadata: dict[str, Any],
        required_format: str,
        required_columns: tuple[str, ...] = (),
    ) -> BioArtifactDraft:
        self._validate_output(
            relative_path=relative_path,
            content=content,
            required_format=required_format,
            required_columns=required_columns,
        )
        parameter_digest = f"sha256:{hashlib.sha256(json.dumps(metadata.get('parameters') or {}, sort_keys=True, default=str).encode('utf-8')).hexdigest()}"
        return BioArtifactDraft(
            relative_path=relative_path,
            kind=kind,
            title=title,
            content=content,
            format=format,
            metadata={
                "source": "host_supervised_bio_tools_sdk",
                "format": format,
                "tool_version": self.tool_version,
                "command_template": metadata.get("tool_name"),
                "sanitized_args": dict(metadata.get("parameters") or {}),
                "parameter_digest": parameter_digest,
                "resource_estimate": {"cpu": 2, "memory_gb": 4, "max_runtime_minutes": 30},
                **metadata,
            },
        )

    def _validate_output(
        self,
        *,
        relative_path: str,
        content: str,
        required_format: str,
        required_columns: tuple[str, ...],
    ) -> None:
        if not content.strip():
            raise self._failure(
                "bio_tools.output",
                "declared_output_missing",
                f"Declared output {relative_path!r} is empty.",
                "Inspect tool logs and rerun with corrected inputs.",
                "bio_tools_output_validation",
            )
        if required_format == "fasta" and not content.lstrip().startswith(">"):
            raise self._failure("bio_tools.output", "invalid_fasta", f"Output {relative_path!r} is not FASTA.", "Regenerate the output.", "bio_tools_output_validation")
        if required_format == "hmm" and not content.startswith("HMMER"):
            raise self._failure("bio_tools.output", "invalid_hmm", f"Output {relative_path!r} is not HMMER format.", "Regenerate the output.", "bio_tools_output_validation")
        if required_format == "csv" and required_columns:
            header = content.splitlines()[0].split(",") if content.splitlines() else []
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise self._failure(
                    "bio_tools.output",
                    "invalid_csv",
                    f"Output {relative_path!r} is missing required column(s): {missing}.",
                    "Do not register malformed CSV output as successful.",
                    "bio_tools_output_validation",
                    details={"missing_columns": missing},
                )

    def _result(
        self,
        *,
        operation: str,
        summary: dict[str, Any],
        artifacts: tuple[BioArtifactDraft, ...],
        warnings: tuple[dict[str, Any], ...] = (),
    ) -> BioSdkResult:
        return BioSdkResult(
            provider="bio_tools",
            operation=operation,
            summary={
                **summary,
                "expected_outputs": [artifact.relative_path for artifact in artifacts],
                "warning_count": len(warnings),
            },
            warnings=warnings,
            artifacts=artifacts,
        )

    def _failure(
        self,
        sdk_method: str,
        error_type: str,
        message: str,
        hint: str,
        stage: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type=error_type,
            message=message,
            hint=hint,
            stage=stage,
            retryable=retryable,
            sdk_method=sdk_method,
            details={} if details is None else details,
        )


@dataclass(frozen=True, slots=True)
class PreprocessArtifactDraft:
    source_artifact_id: str
    operation: str
    storage_uri: str
    relative_path: str
    input_format: str
    output_format: str
    tool: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    required_artifacts: tuple[SessionArtifactRecord, ...]
    created_artifacts: tuple[PreprocessArtifactDraft, ...] = ()


class PreprocessAdapter(Protocol):
    def preprocess_for_execution(
        self,
        *,
        session_id: str,
        invocation_id: str,
        handoff: "ExecutionHandoff",
        required_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> PreprocessResult: ...


def _find_required_artifact(
    required_artifacts: tuple[SessionArtifactRecord, ...],
    *,
    explicit_id: Any,
    default_index: int,
    slot_name: str,
) -> SessionArtifactRecord:
    if explicit_id is not None:
        requested = str(explicit_id)
        for artifact in required_artifacts:
            if artifact.artifact_id == requested:
                return artifact
        raise ValueError(f"{slot_name} artifact {requested!r} was not provided in required_artifact_ids")
    if len(required_artifacts) > default_index:
        return required_artifacts[default_index]
    raise ValueError(f"{slot_name} requires an artifact id or required_artifact_ids[{default_index}]")


@dataclass(frozen=True, slots=True)
class DefaultPreprocessAdapter:
    output_root: Path = Path(tempfile.gettempdir()) / "openzyme-preprocess"

    def preprocess_for_execution(
        self,
        *,
        session_id: str,
        invocation_id: str,
        handoff: "ExecutionHandoff",
        required_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> PreprocessResult:
        if handoff.catalog_tool_id != "vina":
            return PreprocessResult(required_artifacts=required_artifacts)
        tool_inputs = {} if handoff.tool_inputs is None else dict(handoff.tool_inputs)
        receptor = _find_required_artifact(
            required_artifacts,
            explicit_id=tool_inputs.get("receptor_artifact_id"),
            default_index=0,
            slot_name="vina receptor",
        )
        ligand = _find_required_artifact(
            required_artifacts,
            explicit_id=tool_inputs.get("ligand_artifact_id"),
            default_index=1,
            slot_name="vina ligand",
        )
        replacements: dict[str, PreprocessArtifactDraft] = {}
        created: list[PreprocessArtifactDraft] = []
        for slot_name, artifact, operation in (
            ("receptor", receptor, "prepare_receptor"),
            ("ligand", ligand, "prepare_ligand"),
        ):
            if artifact.storage_uri.lower().endswith(".pdbqt"):
                continue
            draft = self._prepare_artifact(
                session_id=session_id,
                invocation_id=invocation_id,
                slot_name=slot_name,
                artifact=artifact,
                operation=operation,
            )
            replacements[artifact.artifact_id] = draft
            created.append(draft)
        if not created:
            return PreprocessResult(required_artifacts=required_artifacts)
        replacement_records = {
            source_id: SessionArtifactRecord(
                artifact_id=f"{source_id}:preprocess:{_safe_ref(draft.relative_path)}",
                session_id=session_id,
                task_id=None,
                lane_id=None,
                invocation_id=invocation_id,
                run_id=None,
                kind=ArtifactKind.STRUCTURE,
                storage_uri=draft.storage_uri,
                relative_path=draft.relative_path,
                title=PurePosixPath(draft.relative_path).name,
                description=f"{draft.operation} output for {source_id}",
                metadata={
                    "source": "preprocess",
                    "source_artifact_id": draft.source_artifact_id,
                    "operation": draft.operation,
                    "input_format": draft.input_format,
                    "output_format": draft.output_format,
                    "tool": draft.tool,
                    "provenance": draft.metadata,
                },
                created_at=utc_now_iso(),
            )
            for source_id, draft in replacements.items()
        }
        updated = tuple(replacement_records.get(artifact.artifact_id, artifact) for artifact in required_artifacts)
        return PreprocessResult(required_artifacts=updated, created_artifacts=tuple(created))

    def _prepare_artifact(
        self,
        *,
        session_id: str,
        invocation_id: str,
        slot_name: str,
        artifact: SessionArtifactRecord,
        operation: str,
    ) -> PreprocessArtifactDraft:
        from preprocess_backend import prepare_ligand
        from preprocess_backend import prepare_receptor
        from preprocess_backend import smiles_to_3d

        source = Path(artifact.storage_uri)
        input_format = str((artifact.metadata or {}).get("format") or source.suffix.lower().lstrip(".") or "unknown").lower()
        output_dir = self.output_root / session_id / invocation_id
        output_path = output_dir / f"{slot_name}.pdbqt"
        if operation == "prepare_receptor":
            prepared = prepare_receptor(source, output_path)
            provenance = {"source_storage_uri": artifact.storage_uri}
        elif slot_name == "ligand" and input_format in {"smiles", "smi"}:
            smiles = str((artifact.metadata or {}).get("smiles") or "").strip()
            if not smiles:
                smiles = source.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
            intermediate = output_dir / f"{slot_name}.sdf"
            smiles_to_3d(smiles, intermediate)
            prepared = prepare_ligand(intermediate, output_path)
            provenance = {
                "source_storage_uri": artifact.storage_uri,
                "smiles": smiles,
                "intermediate_storage_uri": str(intermediate),
                "intermediate_format": "sdf",
            }
        else:
            prepared = prepare_ligand(source, output_path)
            provenance = {"source_storage_uri": artifact.storage_uri}
        return PreprocessArtifactDraft(
            source_artifact_id=artifact.artifact_id,
            operation=operation,
            storage_uri=str(prepared),
            relative_path=f"preprocess/{invocation_id}/{slot_name}.pdbqt",
            input_format=input_format,
            output_format="pdbqt",
            tool="preprocess-backend",
            metadata=provenance,
        )


@dataclass(frozen=True, slots=True)
class ExecutionHandoff:
    execution_goal: str
    required_artifact_ids: tuple[str, ...] = ()
    context_artifact_ids: tuple[str, ...] = ()
    catalog_tool_id: str = "fpocket"
    tool_inputs: dict[str, Any] | None = None
    execution_mode: str = "auto"
    require_approval: bool = True
    requested_action: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExecutionHandoff":
        return cls(
            execution_goal=str(payload["execution_goal"]),
            required_artifact_ids=tuple(str(value) for value in payload.get("required_artifact_ids", [])),
            context_artifact_ids=tuple(str(value) for value in payload.get("context_artifact_ids", [])),
            catalog_tool_id=str(payload.get("catalog_tool_id", "fpocket")),
            tool_inputs=None if payload.get("tool_inputs") is None else dict(payload.get("tool_inputs") or {}),
            execution_mode=str(payload.get("execution_mode", "auto")),
            require_approval=bool(payload.get("require_approval", True)),
            requested_action=None
            if payload.get("requested_action") is None
            else str(payload.get("requested_action")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_goal": self.execution_goal,
            "required_artifact_ids": list(self.required_artifact_ids),
            "context_artifact_ids": list(self.context_artifact_ids),
            "catalog_tool_id": self.catalog_tool_id,
            "tool_inputs": {} if self.tool_inputs is None else dict(self.tool_inputs),
            "execution_mode": self.execution_mode,
            "require_approval": self.require_approval,
            "requested_action": self.requested_action,
        }


@dataclass(frozen=True, slots=True)
class ExecutionStartResult:
    invocation: EngineInvocation
    run: RunRecord | None
    approval: ApprovalRequest | None
    artifacts: tuple[SessionArtifactRecord, ...] = ()
    parsed_result: ExecutionParsedResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation": self.invocation.to_dict(),
            "run": None if self.run is None else self.run.to_dict(),
            "approval": None if self.approval is None else self.approval.to_dict(),
            "artifacts": [project_artifact_for_agent(artifact) for artifact in self.artifacts],
            "parsed_result": None if self.parsed_result is None else self.parsed_result.to_dict(),
        }


@dataclass(slots=True)
class DefaultExecutionRequestCompiler:
    def compile_request(
        self,
        *,
        handoff: ExecutionHandoff,
        task: Any,
        resolved_required_artifacts: tuple[SessionArtifactRecord, ...],
        resolved_context_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> dict[str, Any]:
        tool_inputs = {} if handoff.tool_inputs is None else dict(handoff.tool_inputs)
        primary_input = None if not resolved_required_artifacts else resolved_required_artifacts[0]
        subject_id = "artifact" if primary_input is None else primary_input.artifact_id
        subject_label = "artifact" if primary_input is None else (
            primary_input.title or primary_input.relative_path or primary_input.artifact_id
        )
        contract = get_hpc_tool_contract(handoff.catalog_tool_id)
        metadata = {
            "catalog_tool_id": handoff.catalog_tool_id,
            "tool_inputs": tool_inputs,
            "tool_contract": _contract_payload(contract),
            "execution_goal": handoff.execution_goal,
            "required_artifact_ids": list(handoff.required_artifact_ids),
            "context_artifact_ids": list(handoff.context_artifact_ids),
            "resolved_artifacts": [artifact.to_dict() for artifact in (*resolved_required_artifacts, *resolved_context_artifacts)],
            "input_artifact_ids": [artifact.artifact_id for artifact in resolved_required_artifacts],
            "preprocess_artifact_ids": [
                artifact.artifact_id
                for artifact in resolved_required_artifacts
                if artifact.metadata and artifact.metadata.get("source") == "preprocess"
            ],
            "task_id": task.task_id,
        }
        if handoff.catalog_tool_id == "fpocket":
            structure = _find_required_artifact(
                resolved_required_artifacts,
                explicit_id=tool_inputs.get("structure_artifact_id"),
                default_index=0,
                slot_name="fpocket structure",
            )
            return {
                "tool_name": "exec.run",
                "runspec": {
                    "name": f"execution-{structure.artifact_id}",
                    "stage": "execution",
                    "command": _render_contract_command(contract, tool_inputs),
                    "execution_mode": handoff.execution_mode,
                    "resources": dict(contract.resources),
                    "inputs": [
                        {
                            "artifact_id": structure.artifact_id,
                            "local_path": structure.storage_uri,
                            "remote_path": _runner_relative_path(contract.input_slots[0].remote_path),
                            "required": True,
                            "stage_to": "work",
                        }
                    ],
                    "expected_outputs": _contract_outputs(contract),
                    "success_checks": [dict(item) for item in contract.success_checks],
                    "failure_signatures": [dict(item) for item in contract.failure_signatures],
                    "metadata": metadata,
                },
            }
        if handoff.catalog_tool_id == "vina":
            receptor = _find_required_artifact(
                resolved_required_artifacts,
                explicit_id=tool_inputs.get("receptor_artifact_id"),
                default_index=0,
                slot_name="vina receptor",
            )
            ligand = _find_required_artifact(
                resolved_required_artifacts,
                explicit_id=tool_inputs.get("ligand_artifact_id"),
                default_index=1,
                slot_name="vina ligand",
            )
            return {
                "tool_name": "exec.run",
                "runspec": {
                    "name": f"execution-{subject_id}",
                    "stage": "execution",
                    "command": _render_contract_command(contract, tool_inputs),
                    "execution_mode": handoff.execution_mode,
                    "resources": dict(contract.resources),
                    "inputs": [
                        {
                            "artifact_id": receptor.artifact_id,
                            "local_path": receptor.storage_uri,
                            "remote_path": _runner_relative_path(contract.input_slots[0].remote_path),
                            "required": True,
                            "stage_to": "work",
                        },
                        {
                            "artifact_id": ligand.artifact_id,
                            "local_path": ligand.storage_uri,
                            "remote_path": _runner_relative_path(contract.input_slots[1].remote_path),
                            "required": True,
                            "stage_to": "work",
                        },
                    ],
                    "expected_outputs": _contract_outputs(contract),
                    "success_checks": [dict(item) for item in contract.success_checks],
                    "failure_signatures": [dict(item) for item in contract.failure_signatures],
                    "metadata": metadata,
                },
            }
        return {
            "tool_name": "exec.run",
            "runspec": {
                "name": f"execution-{subject_id}",
                "stage": "execution",
                "command": ["echo", subject_label],
                "execution_mode": handoff.execution_mode,
                "metadata": metadata,
            },
        }


@dataclass(slots=True)
class DefaultExecutionResultParser:
    def parse_result(
        self,
        *,
        handoff: ExecutionHandoff,
        outcome: ExecutionOutcome,
        artifact_refs: tuple[SessionArtifactRecord, ...],
    ) -> ExecutionParsedResult:
        if handoff.catalog_tool_id == "fpocket":
            pockets_found = int(outcome.raw_result.get("pockets_found") or 1)
            return ExecutionParsedResult(
                result_summary=f"fpocket found {pockets_found} pocket(s) for the selected artifact set.",
                structured_findings={
                    "design_signal": "proceed" if pockets_found > 0 else "revise",
                    "pockets_found": pockets_found,
                    "artifacts": [project_artifact_for_agent(artifact) for artifact in artifact_refs],
                },
            )
        if handoff.catalog_tool_id == "vina":
            affinity_value = outcome.raw_result.get("best_affinity")
            try:
                affinity = float(affinity_value)
            except (TypeError, ValueError):
                affinity = -5.5
            return ExecutionParsedResult(
                result_summary=f"vina completed with best affinity {affinity:.2f} kcal/mol.",
                structured_findings={
                    "design_signal": "proceed" if affinity <= -6.0 else "revise",
                    "best_affinity": affinity,
                    "artifacts": [project_artifact_for_agent(artifact) for artifact in artifact_refs],
                },
            )
        return ExecutionParsedResult(
            result_summary=f"{handoff.catalog_tool_id} execution completed.",
            structured_findings={
                "design_signal": "proceed",
                "artifacts": [project_artifact_for_agent(artifact) for artifact in artifact_refs],
            },
        )


@dataclass(slots=True)
class ExecutionEngine:
    repositories: Any
    runner: ExecutionRunner
    compiler: ExecutionRequestCompiler | None = None
    parser: ExecutionResultParser | None = None
    preprocess_adapter: PreprocessAdapter | None = None
    bio_adapter: BioDatabaseAdapter | None = None
    bio_tools_adapter: BioToolsAdapter | None = None
    event_emitter: Any | None = None
    sandbox_runner: Any | None = None

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="execution",
            tool_names=(
                "execution.pipeline.start",
                "execution.pipeline.status",
            ),
            input_schema={"type": "object", "required": ["task_id", "code_artifact_id"]},
            output_schema={
                "type": "object",
                "required": ["invocation"],
            },
            requires_approval=True,
            supports_background=True,
            idempotency_key_shape="{task_id}:execution:{nonce}",
            produces_artifact_types=("run", "artifact"),
            capability_key="execution",
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        register_execution_tools(registry, self)

    def _load_pipeline_source(self, *, session_id: str, code_artifact_id: str) -> PipelineSource:
        artifact = self.repositories.artifacts.get(code_artifact_id)
        source_metadata = {"source_code_artifact_id": code_artifact_id}
        if artifact is None or artifact.session_id != session_id:
            raise PipelineSourceError(
                error_code="code_artifact_not_found",
                message=f"code artifact {code_artifact_id!r} does not exist in the current session.",
                hint="Create a pipeline source artifact with artifact.create_text and pass its artifact_id as code_artifact_id.",
                source_metadata=source_metadata,
            )
        metadata = dict(artifact.metadata or {})
        source_metadata = {
            "source_code_artifact_id": artifact.artifact_id,
            "source_code_digest": metadata.get("content_digest"),
            "source_code_version": metadata.get("version"),
        }
        if (
            artifact.kind is not ArtifactKind.CODE
            or str(metadata.get("format") or "").lower() != "python"
            or metadata.get("semantic_type") != "pipeline_source"
        ):
            raise PipelineSourceError(
                error_code="invalid_code_artifact",
                message="code_artifact_id must reference a Python pipeline source artifact.",
                hint="Use artifact.create_text to create kind=code, format=python, semantic_type=pipeline_source.",
                source_metadata=source_metadata,
            )
        storage_path = Path(str(artifact.storage_uri or ""))
        if not storage_path.is_file():
            raise PipelineSourceError(
                error_code="code_artifact_content_missing",
                message="code artifact content file is not readable.",
                hint="Create a fresh pipeline source artifact and retry execution.pipeline.start.",
                source_metadata=source_metadata,
            )
        try:
            raw = storage_path.read_bytes()
            code = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PipelineSourceError(
                error_code="code_artifact_not_utf8",
                message="code artifact content is not valid UTF-8.",
                hint="Patch the pipeline source artifact with valid UTF-8 Python source.",
                source_metadata=source_metadata,
            ) from exc
        except OSError as exc:
            raise PipelineSourceError(
                error_code="code_artifact_content_unreadable",
                message=f"code artifact content could not be read: {exc}",
                hint="Create a fresh pipeline source artifact and retry execution.pipeline.start.",
                source_metadata=source_metadata,
            ) from exc
        code_digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        source_code_digest = f"sha256:{code_digest}"
        expected_digest = metadata.get("content_digest")
        if expected_digest is None:
            raise PipelineSourceError(
                error_code="source_code_digest_missing",
                message="code artifact metadata is missing content_digest.",
                hint="Create a fresh pipeline source artifact with artifact.create_text.",
                source_metadata={**source_metadata, "source_code_digest": source_code_digest},
            )
        if str(expected_digest) != source_code_digest:
            raise PipelineSourceError(
                error_code="source_code_digest_mismatch",
                message="code artifact metadata content_digest does not match the stored source content.",
                hint="Do not execute this source artifact; create or patch a fresh pipeline source artifact.",
                source_metadata={
                    **source_metadata,
                    "source_code_digest": str(expected_digest),
                    "actual_source_code_digest": source_code_digest,
                },
            )
        version_value = metadata.get("version")
        try:
            version = None if version_value is None else int(version_value)
        except (TypeError, ValueError):
            version = None
        return PipelineSource(
            artifact=artifact,
            code=code,
            code_digest=code_digest,
            source_code_digest=source_code_digest,
            source_code_version=version,
        )

    def _reload_pipeline_source(self, invocation: EngineInvocation, pipeline: dict[str, Any]) -> PipelineSource:
        code_artifact_id = pipeline.get("source_code_artifact_id")
        if code_artifact_id is None:
            raise PipelineSourceError(
                error_code="missing_code_artifact_id",
                message="persisted execution pipeline input is missing source_code_artifact_id.",
                hint="Retry execution.pipeline.start with code_artifact_id.",
            )
        source = self._load_pipeline_source(
            session_id=invocation.session_id,
            code_artifact_id=str(code_artifact_id),
        )
        approved_digest = pipeline.get("source_code_digest")
        if approved_digest is not None and str(approved_digest) != source.source_code_digest:
            raise PipelineSourceError(
                error_code="source_code_digest_mismatch",
                message="current code artifact digest does not match the approved pipeline source digest.",
                hint="Create a new dry-run plan for the updated source artifact before executing.",
                source_metadata={
                    **source.metadata(),
                    "approved_source_code_digest": approved_digest,
                },
            )
        return source

    def start_pipeline(
        self,
        *,
        session_id: str,
        task_id: str,
        code_artifact_id: str | None = None,
        code: str | None = None,
        inputs: dict[str, Any] | None = None,
        dry_run: bool = False,
        invocation_id: str | None = None,
        lane_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ExecutionStartResult:
        pipeline_inputs = dict(inputs or {})
        if code is not None:
            code_digest = hashlib.sha256(str(code).encode("utf-8")).hexdigest()
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="unsupported_inline_pipeline_code",
                message="execution.pipeline.start does not accept inline code.",
                hint="Create a pipeline source artifact with artifact.create_text or artifact.patch_text and pass code_artifact_id.",
            )
        if code_artifact_id is None:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest="missing_code_artifact_id",
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="missing_code_artifact_id",
                message="execution.pipeline.start requires code_artifact_id.",
                hint="Create a pipeline source artifact with artifact.create_text and pass its artifact_id.",
            )
        try:
            source = self._load_pipeline_source(session_id=session_id, code_artifact_id=str(code_artifact_id))
        except PipelineSourceError as exc:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=str(exc.source_metadata.get("actual_source_code_digest") or exc.source_metadata.get("source_code_digest") or exc.error_code),
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code=exc.error_code,
                message=exc.message,
                hint=exc.hint,
                error_type=exc.error_code,
                stage=exc.stage,
                retryable=exc.retryable,
                source_metadata=exc.source_metadata,
            )
        code = source.code
        code_digest = source.code_digest
        source_metadata = source.metadata()
        forbidden_network = self._forbidden_pipeline_network_usage(code)
        if forbidden_network:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="unsupported_sandbox_network_call",
                message="Pipeline code cannot perform direct network or provider SDK calls inside the sandbox.",
                hint=(
                    "Use openzyme_pipeline.bio for NCBI, UniProt, or EBI HMMER requests. "
                    f"Rejected import(s): {forbidden_network}"
                ),
                error_type="unsupported_sandbox_network_call",
                stage="pipeline_static_policy",
                retryable=False,
                source_metadata=source_metadata,
            )
        forbidden_process = self._forbidden_pipeline_process_usage(code)
        if forbidden_process:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="unsupported_sandbox_process_call",
                message="Pipeline code cannot call subprocess, shell, or bioinformatics binaries directly.",
                hint=(
                    "Use openzyme_pipeline.bio_tools for MAFFT, CD-HIT, and HMMER CLI operations. "
                    f"Rejected usage: {forbidden_process}"
                ),
                error_type="unsupported_sandbox_process_call",
                stage="pipeline_static_policy",
                retryable=False,
                source_metadata=source_metadata,
            )
        if "handoff" in pipeline_inputs:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="unsupported_pipeline_handoff",
                message="execution.pipeline.start no longer accepts legacy execution handoff input.",
                hint="Use executor-authored pipeline code and consult docs.search for execution pipeline SDK docs.",
                source_metadata=source_metadata,
            )
        declared_artifact_ids = {
            str(value)
            for value in [
                *list(pipeline_inputs.get("artifact_ids") or []),
                *list(pipeline_inputs.get("context_artifact_ids") or []),
            ]
        }
        missing_artifact_ids = [
            artifact_id
            for artifact_id in self._literal_pipeline_artifact_get_ids(code)
            if artifact_id not in declared_artifact_ids
        ]
        if missing_artifact_ids:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="missing_pipeline_artifact_inputs",
                message="pipeline code reads artifacts that were not declared in inputs.artifact_ids or inputs.context_artifact_ids.",
                hint=(
                    "Add inputs={'artifact_ids': [...] } to execution.pipeline.start for required artifact reads. "
                    f"Missing artifact ids: {missing_artifact_ids}"
                ),
                source_metadata=source_metadata,
            )
        execution_plan = self._build_execution_plan(
            code=code,
            code_digest=code_digest,
            inputs=pipeline_inputs,
            source_metadata=source_metadata,
        )
        plan_validation_error = self._validate_pipeline_plan_inputs(
            session_id=session_id,
            execution_plan=execution_plan,
        )
        if plan_validation_error is not None:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code=str(plan_validation_error["type"]),
                message=str(plan_validation_error["message"]),
                hint=str(plan_validation_error["hint"]),
                error_type=str(plan_validation_error["type"]),
                stage=str(plan_validation_error["stage"]),
                retryable=bool(plan_validation_error["retryable"]),
                sdk_method=plan_validation_error.get("sdk_method"),
                source_metadata=source_metadata,
            )
        pipeline_metadata = {
            "code_digest": code_digest,
            **source_metadata,
            "inputs": pipeline_inputs,
            "dry_run": dry_run,
            "execution_plan": execution_plan,
            "plan_digest": execution_plan["plan_digest"],
            "sdk_operation_log": execution_plan["operations"],
            "approved_operation_keys": [],
            "approved_plan_digest": None,
            "completed_operations": {},
        }
        if dry_run:
            return self._start_pipeline_dry_run(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                pipeline_metadata=pipeline_metadata,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
            )
        if execution_plan["approval_requirements"]:
            return self._start_pipeline_waiting_plan_approval(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                pipeline_metadata=pipeline_metadata,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
            )
        return self._start_pipeline_supervisor(
            session_id=session_id,
            task_id=task_id,
            code=code,
            code_digest=code_digest,
            pipeline_metadata=pipeline_metadata,
            invocation_id=invocation_id,
            lane_id=lane_id,
            idempotency_key=idempotency_key,
        )

    def start_execution(
        self,
        *,
        session_id: str,
        task_id: str,
        handoff: dict[str, Any],
        invocation_id: str | None = None,
        lane_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ExecutionStartResult:
        session = self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        handoff_model = ExecutionHandoff.from_payload(handoff)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        approval = None
        approval_id = None
        invocation_status = EngineInvocationStatus.RUNNING
        if handoff_model.require_approval:
            approval_id = f"appr_{uuid4().hex[:12]}"
            approval = ApprovalRequest(
                approval_id=approval_id,
                session_id=session_id,
                task_id=task_id,
                lane_id=effective_lane_id,
                kind="execution_launch",
                requested_action=handoff_model.requested_action
                or f"Approve execution launch for task {task.subject}",
                status=ApprovalRequestStatus.PENDING,
                request_ref=f"artifact://approvals/{approval_id}.json",
                resolution_ref=None,
                created_at=now,
            )
            self.repositories.approvals.save(approval)
            invocation_status = EngineInvocationStatus.WAITING_APPROVAL
            self._emit(
                "approval.requested",
                {
                    "approval_id": approval.approval_id,
                    "task_id": approval.task_id,
                    "lane_id": approval.lane_id,
                    "kind": approval.kind,
                },
            )
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=invocation_status,
            input_ref=input_id,
            output_ref=None,
            approval_id=approval_id,
            idempotency_key=idempotency_key or f"{task_id}:execution:{uuid4().hex[:8]}",
            started_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_input",
                payload={"task_id": task_id, "lane_id": effective_lane_id, "handoff": handoff_model.to_dict()},
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "engine.invocation.started",
            {"invocation_id": invocation_id, "engine_name": self.descriptor.engine_name, "task_id": task_id},
        )
        if approval is not None:
            return ExecutionStartResult(invocation=invocation, run=None, approval=approval)
        return self._submit_execution(session=session, task=task, invocation=invocation, handoff=handoff_model)

    def continue_after_approval(self, *, invocation_id: str, resolution: str | None = None) -> ExecutionStartResult:
        invocation = self._require_invocation(invocation_id)
        session = self._require_session(invocation.session_id)
        task = self._require_task(invocation.session_id, str(invocation.task_id))
        input_payload = self._require_input_payload(invocation)
        pipeline_payload = dict(input_payload.get("pipeline") or {})
        if pipeline_payload and "handoff" not in input_payload and self.sandbox_runner is not None:
            if invocation.status.is_terminal:
                runs = self.repositories.runs.list_by_invocation(invocation.session_id, invocation.invocation_id)
                artifacts: list[SessionArtifactRecord] = []
                for run in runs:
                    artifacts.extend(self.repositories.artifacts.list_by_run(run.run_id))
                parsed = None
                if invocation.output_ref is not None:
                    output_document = self.repositories.engine_documents.get(invocation.output_ref)
                    if output_document is not None:
                        payload = dict(output_document.payload.get("pipeline") or {})
                        parsed = ExecutionParsedResult(
                            result_summary=str(payload.get("terminal_summary") or invocation.status.value),
                            structured_findings=payload,
                        )
                return ExecutionStartResult(
                    invocation=invocation,
                    run=None if not runs else runs[-1],
                    approval=self._load_approval(invocation),
                    artifacts=tuple(artifacts),
                    parsed_result=parsed,
                )
            approval = self._load_approval(invocation)
            self._record_pipeline_approval_resolution(invocation, approval, resolution)
            if approval is not None and approval.status is ApprovalRequestStatus.APPROVED:
                refreshed = self._require_invocation(invocation.invocation_id)
                running = self._replace_invocation(refreshed, status=EngineInvocationStatus.RUNNING, finished_at=None)
                self.repositories.invocations.save(running)
                try:
                    source = self._reload_pipeline_source(running, pipeline_payload)
                except PipelineSourceError as exc:
                    return self._finalize_pipeline_sdk_failure(
                        invocation=running,
                        failure=PipelineSdkFailure(
                            error_type=exc.error_code,
                            message=exc.message,
                            hint=exc.hint,
                            stage=exc.stage,
                            retryable=exc.retryable,
                        ),
                    )
                return self._run_pipeline_supervisor(
                    session=session,
                    task=task,
                    invocation=running,
                    code=source.code,
                )
            if approval is not None and approval.status is ApprovalRequestStatus.PENDING:
                return ExecutionStartResult(invocation=invocation, run=None, approval=approval)
            cancelled = self._replace_invocation(invocation, status=EngineInvocationStatus.CANCELLED, finished_at=utc_now_iso())
            self.repositories.invocations.save(cancelled)
            self._emit(
                "execution.pipeline.failed",
                {"invocation_id": cancelled.invocation_id, "status": cancelled.status.value},
            )
            return ExecutionStartResult(invocation=cancelled, run=None, approval=approval)
        handoff = self._load_handoff(invocation)
        approval = None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)
        self._update_input_document(invocation, resolution=resolution)
        if approval is None:
            running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
            self.repositories.invocations.save(running)
            return self._submit_execution(session=session, task=task, invocation=running, handoff=handoff)
        if approval.status is ApprovalRequestStatus.APPROVED:
            running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
            self.repositories.invocations.save(running)
            self._emit(
                "engine.invocation.updated",
                {"invocation_id": running.invocation_id, "engine_name": running.engine_name, "status": "running"},
            )
            return self._submit_execution(session=session, task=task, invocation=running, handoff=handoff)
        if approval.status is ApprovalRequestStatus.PENDING:
            waiting = self._replace_invocation(invocation, status=EngineInvocationStatus.WAITING_APPROVAL, finished_at=None)
            self.repositories.invocations.save(waiting)
            return ExecutionStartResult(invocation=waiting, run=None, approval=approval)
        cancelled = self._replace_invocation(invocation, status=EngineInvocationStatus.CANCELLED, finished_at=utc_now_iso())
        self.repositories.invocations.save(cancelled)
        self._emit(
            "engine.invocation.completed",
            {"invocation_id": cancelled.invocation_id, "engine_name": cancelled.engine_name, "status": "cancelled"},
        )
        return ExecutionStartResult(invocation=cancelled, run=None, approval=approval)

    def get_pipeline_status(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._require_invocation(invocation_id)
        payload = invocation.to_dict()
        if invocation.status is EngineInvocationStatus.WAITING_APPROVAL:
            approval = None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)
            payload["approval"] = None if approval is None else approval.to_dict()
            return payload
        run = self.repositories.runs.get_by_invocation(invocation.session_id, invocation.invocation_id)
        if run is None:
            return payload
        if invocation.status.is_terminal and invocation.output_ref is not None:
            output_document = self.repositories.engine_documents.get(invocation.output_ref)
            payload["run"] = run.to_dict()
            payload["artifacts"] = [
                project_artifact_for_agent(artifact)
                for artifact in self.repositories.artifacts.list_by_invocation(
                    invocation.session_id, invocation.invocation_id
                )
            ]
            if output_document is not None:
                payload["output_payload"] = sanitize_private_artifact_fields(output_document.payload)
                output_payload = dict(payload["output_payload"])
                pipeline = output_payload.get("pipeline")
                if isinstance(pipeline, dict):
                    payload["details"] = pipeline
                    payload["parsed_result"] = pipeline.get("parsed_result")
                    payload["output_artifact_ids"] = list(
                        pipeline.get("output_artifact_ids") or []
                    )
                runs_payload = output_payload.get("runs") or [
                    item.to_dict()
                    for item in self.repositories.runs.list_by_invocation(
                        invocation.session_id, invocation.invocation_id
                    )
                ]
                payload["runs"] = sanitize_private_artifact_fields(runs_payload)
            return payload
        reconciled = self.reconcile_execution(invocation_id)
        return reconciled.to_dict()

    def reconcile_execution(self, invocation_id: str) -> ExecutionStartResult:
        invocation = self._require_invocation(invocation_id)
        if invocation.status is EngineInvocationStatus.WAITING_APPROVAL:
            approval = None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)
            return ExecutionStartResult(invocation=invocation, run=None, approval=approval)
        run = self._require_run(invocation)
        status = self.runner.get_execution_status(
            run_id=run.runner_run_id,
            remote_run_dir=run.remote_run_dir,
            job_id=run.runner_run_id if run.execution_mode == "sbatch" else None,
        )
        updated_run = RunRecord(
            run_id=run.run_id,
            session_id=run.session_id,
            task_id=run.task_id,
            lane_id=run.lane_id,
            invocation_id=run.invocation_id,
            approval_id=run.approval_id,
            engine_name=run.engine_name,
            runner_run_id=run.runner_run_id,
            status=status.status,
            execution_mode=run.execution_mode,
            remote_run_dir=status.remote_run_dir,
            summary=run.summary,
            created_at=run.created_at,
            updated_at=utc_now_iso(),
            finished_at=run.finished_at,
        )
        self.repositories.runs.save(updated_run)
        if not status.status.is_terminal:
            running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
            self.repositories.invocations.save(running)
            return ExecutionStartResult(invocation=running, run=updated_run, approval=self._load_approval(running))
        input_payload = self._require_input_payload(invocation)
        runspec = dict((input_payload.get("request") or {}).get("runspec") or {})
        if status.status is RunStatus.SUCCEEDED:
            fetched = self.runner.fetch_execution_artifacts(
                run_id=run.runner_run_id,
                remote_run_dir=run.remote_run_dir,
                job_id=run.runner_run_id if run.execution_mode == "sbatch" else None,
                runspec=runspec,
            )
            self._emit(
                "execution.artifacts.fetched",
                {
                    "invocation_id": invocation.invocation_id,
                    "run_id": run.run_id,
                    "runner_run_id": run.runner_run_id,
                    "artifact_count": len(fetched.artifacts),
                    "relative_paths": [artifact.relative_path for artifact in fetched.artifacts],
                },
            )
            return self._finalize_terminal(
                invocation=invocation,
                run=updated_run,
                handoff=self._load_handoff(invocation),
                outcome=fetched,
            )
        terminal_outcome = ExecutionOutcome(
            run_id=status.run_id,
            status=status.status,
            execution_mode=run.execution_mode,
            remote_run_dir=status.remote_run_dir,
            raw_result=status.raw_result,
            artifacts=(),
            job_id=status.job_id,
            exit_code=status.exit_code,
        )
        return self._finalize_terminal(
            invocation=invocation,
            run=updated_run,
            handoff=self._load_handoff(invocation),
            outcome=terminal_outcome,
        )

    def _start_pipeline_supervisor(
        self,
        *,
        session_id: str,
        task_id: str,
        code: str,
        code_digest: str,
        pipeline_metadata: dict[str, Any],
        invocation_id: str | None,
        lane_id: str | None,
        idempotency_key: str | None,
    ) -> ExecutionStartResult:
        session = self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        resolved_idempotency_key = idempotency_key or self._pipeline_idempotency_key(
            task_id=task_id,
            code_digest=code_digest,
            inputs=dict(pipeline_metadata.get("inputs") or {}),
            phase="execute",
        )
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=EngineInvocationStatus.RUNNING,
            input_ref=input_id,
            output_ref=None,
            approval_id=None,
            idempotency_key=resolved_idempotency_key,
            started_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_input",
                payload={
                    "task_id": task_id,
                    "lane_id": effective_lane_id,
                    "pipeline": pipeline_metadata,
                },
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "execution.pipeline.started",
            {
                "invocation_id": invocation_id,
                "task_id": task_id,
                "code_digest": code_digest,
                "source_code_artifact_id": pipeline_metadata.get("source_code_artifact_id"),
                "source_code_digest": pipeline_metadata.get("source_code_digest"),
                "source_code_version": pipeline_metadata.get("source_code_version"),
            },
        )
        self._emit(
            "engine.invocation.started",
            {"invocation_id": invocation_id, "engine_name": self.descriptor.engine_name, "task_id": task_id},
        )
        return self._run_pipeline_supervisor(session=session, task=task, invocation=invocation, code=code)

    def _start_pipeline_waiting_plan_approval(
        self,
        *,
        session_id: str,
        task_id: str,
        code_digest: str,
        pipeline_metadata: dict[str, Any],
        invocation_id: str | None,
        lane_id: str | None,
        idempotency_key: str | None,
    ) -> ExecutionStartResult:
        self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        approval_id = f"appr_{uuid4().hex[:12]}"
        plan = dict(pipeline_metadata.get("execution_plan") or {})
        resolved_idempotency_key = idempotency_key or self._pipeline_idempotency_key(
            task_id=task_id,
            code_digest=code_digest,
            inputs=dict(pipeline_metadata.get("inputs") or {}),
            phase="execute",
        )
        existing_invocation = self._find_invocation_by_idempotency_key(
            session_id=session_id,
            idempotency_key=resolved_idempotency_key,
        )
        if existing_invocation is not None:
            return ExecutionStartResult(
                invocation=existing_invocation,
                run=None,
                approval=self._load_approval(existing_invocation),
                parsed_result=ExecutionParsedResult(
                    result_summary="Pipeline invocation already exists for this execution plan.",
                    structured_findings={"plan": plan},
                ),
            )
        approval = ApprovalRequest(
            approval_id=approval_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            kind="execution_pipeline_plan",
            requested_action=(
                f"Approve execution pipeline plan {plan.get('plan_digest')} for task {task.subject}. "
                f"HPC operations: {[item.get('method') for item in plan.get('hpc_operations', [])]}"
            ),
            status=ApprovalRequestStatus.PENDING,
            request_ref=f"artifact://approvals/{approval_id}.json",
            resolution_ref=None,
            created_at=now,
        )
        self.repositories.approvals.save(approval)
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=EngineInvocationStatus.WAITING_APPROVAL,
            input_ref=input_id,
            output_ref=None,
            approval_id=approval_id,
            idempotency_key=resolved_idempotency_key,
            started_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_input",
                payload={
                    "task_id": task_id,
                    "lane_id": effective_lane_id,
                    "pipeline": {
                        **pipeline_metadata,
                        "approval_id": approval_id,
                        "sandbox_status": "waiting_approval",
                    },
                },
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "approval.requested",
            {
                "approval_id": approval.approval_id,
                "task_id": approval.task_id,
                "lane_id": approval.lane_id,
                "kind": approval.kind,
            },
        )
        self._emit(
            "engine.invocation.started",
            {"invocation_id": invocation_id, "engine_name": self.descriptor.engine_name, "task_id": task_id},
        )
        return ExecutionStartResult(
            invocation=invocation,
            run=None,
            approval=approval,
            parsed_result=ExecutionParsedResult(
                result_summary="Pipeline plan is waiting for approval.",
                structured_findings={"plan": plan},
            ),
        )

    def _run_pipeline_supervisor(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        code: str,
    ) -> ExecutionStartResult:
        input_payload = self._require_input_payload(invocation)
        pipeline = dict(input_payload.get("pipeline") or {})
        pipeline_inputs = dict(pipeline.get("inputs") or {})
        artifact_ids = tuple(str(value) for value in pipeline_inputs.get("artifact_ids") or [])
        context_ids = tuple(str(value) for value in pipeline_inputs.get("context_artifact_ids") or [])
        sandbox_inputs = self._resolve_artifacts(session.session_id, (*artifact_ids, *context_ids))
        if self.sandbox_runner is None:
            raise RuntimeError("pipeline sandbox runner is not configured")
        preflight = self.sandbox_runner.preflight() if hasattr(self.sandbox_runner, "preflight") else None
        if preflight is not None and not preflight.ok:
            raise RuntimeError(f"pipeline sandbox preflight failed: {preflight.message}")
        try:
            outcome = self.sandbox_runner.run_pipeline(
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                code=code,
                inputs=sandbox_inputs,
                control_handler=lambda method, params: self._handle_pipeline_sdk_call(
                    session=session,
                    task=task,
                    invocation_id=invocation.invocation_id,
                    method=method,
                    params=params,
                ),
            )
        except PipelineApprovalRequired as exc:
            waiting = self.repositories.invocations.get(invocation.invocation_id) or invocation
            return ExecutionStartResult(invocation=waiting, run=None, approval=exc.approval)
        except PipelineSdkFailure as exc:
            return self._finalize_pipeline_sdk_failure(invocation=invocation, failure=exc)
        except Exception as exc:
            raise RuntimeError(
                f"pipeline sandbox raised {type(exc).__name__}: {exc}"
            ) from exc
        waiting = self.repositories.invocations.get(invocation.invocation_id)
        if waiting is not None and waiting.status is EngineInvocationStatus.WAITING_APPROVAL:
            return ExecutionStartResult(invocation=waiting, run=None, approval=self._load_approval(waiting))
        return self._finalize_pipeline_terminal(invocation=invocation, outcome=outcome)

    def _handle_pipeline_sdk_call(
        self,
        *,
        session: Any,
        task: Any,
        invocation_id: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        invocation = self._require_invocation(invocation_id)
        if method in {"preprocess.convert_format", "preprocess.prepare_receptor", "preprocess.prepare_ligand", "preprocess.smiles_to_3d"}:
            return self._run_pipeline_preprocess(session=session, invocation=invocation, method=method, params=params)
        if method in {"bio.ncbi_fetch_proteins", "bio.uniprot_fetch", "bio.hmmer_search"}:
            return self._run_pipeline_bio(session=session, invocation=invocation, method=method, params=params)
        if method in {"bio_tools.cdhit", "bio_tools.mafft", "bio_tools.hmmbuild", "bio_tools.hmmalign", "bio_tools.hmmer_search_cli"}:
            return self._run_pipeline_bio_tool(session=session, invocation=invocation, method=method, params=params)
        if method in {"hpc.fpocket", "hpc.vina"}:
            return self._run_pipeline_hpc(session=session, task=task, invocation=invocation, method=method, params=params)
        if method == "run.wait":
            run = self.repositories.runs.get(str(params["run_id"]))
            if run is None:
                raise ValueError(f"run {params['run_id']!r} does not exist")
            return run.to_dict()
        if method == "run.fetch_artifacts":
            return [
                self._sandbox_safe_artifact(artifact)
                for artifact in self.repositories.artifacts.list_by_run(str(params["run_id"]))
            ]
        raise ValueError(f"unsupported SDK operation {method!r}")

    def _run_pipeline_bio(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        operation_key = self._pipeline_operation_key(method, params)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        completed = dict(pipeline.get("completed_operations") or {})
        if operation_key in completed:
            return dict(completed[operation_key])
        adapter = self.bio_adapter or DeterministicBioDatabaseAdapter()
        retrieved_at = utc_now_iso()
        if method == "bio.ncbi_fetch_proteins":
            result = adapter.ncbi_fetch_proteins(
                accessions=tuple(str(value) for value in list(params.get("accessions") or [])),
                fields=tuple(str(value) for value in list(params.get("fields") or [])),
                retrieved_at=retrieved_at,
            )
        elif method == "bio.uniprot_fetch":
            batch_size_value = params.get("batch_size")
            try:
                batch_size = None if batch_size_value is None else int(batch_size_value)
            except (TypeError, ValueError) as exc:
                raise PipelineSdkFailure(
                    error_type="invalid_batch_size",
                    message="bio.uniprot_fetch batch_size must be an integer.",
                    hint="Retry with batch_size omitted or set to a positive integer.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"batch_size": batch_size_value},
                ) from exc
            result = adapter.uniprot_fetch(
                accessions=tuple(str(value) for value in list(params.get("accessions") or [])),
                fields=tuple(str(value) for value in list(params.get("fields") or [])),
                batch_size=batch_size,
                retrieved_at=retrieved_at,
            )
        elif method == "bio.hmmer_search":
            hmm_artifact_id = str(params.get("hmm_artifact_id") or "")
            hmm_artifact = self.repositories.artifacts.get(hmm_artifact_id)
            if hmm_artifact is None or hmm_artifact.session_id != session.session_id:
                raise PipelineSdkFailure(
                    error_type="invalid_hmm_artifact",
                    message=f"HMM artifact {hmm_artifact_id!r} is not available in this session.",
                    hint="Pass an existing HMM artifact id produced or uploaded in this session.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"hmm_artifact_id": hmm_artifact_id},
                )
            hmm_format = str((hmm_artifact.metadata or {}).get("format") or "").lower()
            if hmm_format != "hmm" and not hmm_artifact.relative_path.lower().endswith(".hmm"):
                raise PipelineSdkFailure(
                    error_type="invalid_hmm_artifact",
                    message=f"HMM artifact {hmm_artifact_id!r} must declare format=hmm or use a .hmm relative path.",
                    hint="Pass an HMM artifact produced by bio_tools.hmmbuild or an uploaded HMM file.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"hmm_artifact_id": hmm_artifact_id, "format": hmm_format},
                )
            result = adapter.hmmer_search(
                hmm_artifact=hmm_artifact,
                database=str(params.get("database") or ""),
                params=dict(params.get("params") or {}),
                retrieved_at=retrieved_at,
            )
        else:
            raise ValueError(f"unsupported bio SDK operation {method!r}")
        records = self._persist_bio_artifacts(
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            operation_key=operation_key,
            drafts=result.artifacts,
            request_metadata={
                "pipeline_invocation_id": invocation.invocation_id,
                "sdk_method": method,
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "pipeline_step_id": operation_key,
                "input_artifact_ids": list((pipeline.get("inputs") or {}).get("artifact_ids") or []),
                "preprocess_artifact_ids": list(pipeline.get("preprocess_artifact_ids") or []),
            },
        )
        payload = {
            "tool_id": method,
            "provider": result.provider,
            "status": RunStatus.SUCCEEDED.value,
            "operation_key": operation_key,
            "summary": result.summary,
            "warnings": list(result.warnings),
            "artifact_count": len(records),
            "artifact_ids": [record.artifact_id for record in records],
            "artifacts": [project_artifact_for_agent(record) for record in records],
        }
        self._record_pipeline_completed_operation(invocation, operation_key, payload)
        self._append_pipeline_list(invocation, "bio_artifact_ids", [record.artifact_id for record in records])
        self._emit(
            "execution.pipeline.step.completed",
            {
                "invocation_id": invocation.invocation_id,
                "operation": method,
                "operation_key": operation_key,
                "artifact_ids": [record.artifact_id for record in records],
                "warning_count": len(result.warnings),
            },
        )
        return payload

    def _run_pipeline_bio_tool(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        operation_key = self._pipeline_operation_key(method, params)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        completed = dict(pipeline.get("completed_operations") or {})
        if operation_key in completed:
            return dict(completed[operation_key])
        adapter = self.bio_tools_adapter or DeterministicBioToolsAdapter()
        retrieved_at = utc_now_iso()
        if method == "bio_tools.cdhit":
            try:
                identity = float(params.get("identity") or 0)
            except (TypeError, ValueError) as exc:
                raise PipelineSdkFailure(
                    error_type="invalid_tool_parameter",
                    message="bio_tools.cdhit identity must be numeric.",
                    hint="Retry with an identity threshold such as 0.9.",
                    stage="bio_tools_input_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"identity": params.get("identity")},
                ) from exc
            result = adapter.cdhit(
                input_fasta=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("input_fasta_artifact_id") or ""),
                    sdk_method=method,
                ),
                identity=identity,
                mode=str(params.get("mode") or "protein"),
                retrieved_at=retrieved_at,
            )
        elif method == "bio_tools.mafft":
            result = adapter.mafft(
                input_fasta=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("input_fasta_artifact_id") or ""),
                    sdk_method=method,
                ),
                params=dict(params.get("params") or {}),
                retrieved_at=retrieved_at,
            )
        elif method == "bio_tools.hmmbuild":
            result = adapter.hmmbuild(
                alignment=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("alignment_artifact_id") or ""),
                    sdk_method=method,
                ),
                params=dict(params.get("params") or {}),
                retrieved_at=retrieved_at,
            )
        elif method == "bio_tools.hmmalign":
            result = adapter.hmmalign(
                hmm=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("hmm_artifact_id") or ""),
                    sdk_method=method,
                ),
                fasta=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("fasta_artifact_id") or ""),
                    sdk_method=method,
                ),
                params=dict(params.get("params") or {}),
                retrieved_at=retrieved_at,
            )
        elif method == "bio_tools.hmmer_search_cli":
            result = adapter.hmmer_search_cli(
                hmm=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("hmm_artifact_id") or ""),
                    sdk_method=method,
                ),
                target_fasta=self._require_pipeline_artifact(
                    session_id=session.session_id,
                    artifact_id=str(params.get("target_fasta_artifact_id") or ""),
                    sdk_method=method,
                ),
                params=dict(params.get("params") or {}),
                retrieved_at=retrieved_at,
            )
        else:
            raise ValueError(f"unsupported bio tools SDK operation {method!r}")
        records = self._persist_bio_artifacts(
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            operation_key=operation_key,
            drafts=result.artifacts,
            request_metadata={
                "pipeline_invocation_id": invocation.invocation_id,
                "sdk_method": method,
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "pipeline_step_id": operation_key,
                "input_artifact_ids": list((pipeline.get("inputs") or {}).get("artifact_ids") or []),
                "preprocess_artifact_ids": list(pipeline.get("preprocess_artifact_ids") or []),
                "bio_artifact_ids": list(pipeline.get("bio_artifact_ids") or []),
            },
        )
        payload = {
            "tool_id": method,
            "provider": result.provider,
            "status": RunStatus.SUCCEEDED.value,
            "operation_key": operation_key,
            "summary": result.summary,
            "warnings": list(result.warnings),
            "artifact_count": len(records),
            "artifact_ids": [record.artifact_id for record in records],
            "artifacts": [project_artifact_for_agent(record) for record in records],
        }
        self._record_pipeline_completed_operation(invocation, operation_key, payload)
        self._append_pipeline_list(invocation, "bio_artifact_ids", [record.artifact_id for record in records])
        self._emit(
            "execution.pipeline.step.completed",
            {
                "invocation_id": invocation.invocation_id,
                "operation": method,
                "operation_key": operation_key,
                "artifact_ids": [record.artifact_id for record in records],
                "warning_count": len(result.warnings),
            },
        )
        return payload

    def _run_pipeline_hpc(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        operation_key = self._pipeline_operation_key(method, params)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        completed = dict(pipeline.get("completed_operations") or {})
        if operation_key in completed:
            return dict(completed[operation_key])
        if method == "hpc.fpocket":
            self._validate_fpocket_artifact(str(params["structure_artifact_id"]))
        approved = set(str(value) for value in list(pipeline.get("approved_operation_keys") or []))
        if operation_key not in approved and not self._pipeline_hpc_covered_by_approved_plan(pipeline=pipeline, method=method, params=params):
            approval = self._request_pipeline_approval(invocation=invocation, method=method, params=params, operation_key=operation_key)
            raise PipelineApprovalRequired(approval)
        tool_params = dict(params.get("params") or {})
        if method == "hpc.fpocket":
            handoff = ExecutionHandoff(
                execution_goal="Run fpocket from execution pipeline.",
                required_artifact_ids=(str(params["structure_artifact_id"]),),
                catalog_tool_id="fpocket",
                tool_inputs={"structure_artifact_id": str(params["structure_artifact_id"]), **tool_params},
                require_approval=False,
            )
        else:
            receptor_id = str(params["receptor_artifact_id"])
            ligand_id = str(params["ligand_artifact_id"])
            self._require_pdbqt_artifact(receptor_id, slot_name="vina receptor")
            self._require_pdbqt_artifact(ligand_id, slot_name="vina ligand")
            handoff = ExecutionHandoff(
                execution_goal="Run vina from execution pipeline.",
                required_artifact_ids=(receptor_id, ligand_id),
                catalog_tool_id="vina",
                tool_inputs={"receptor_artifact_id": receptor_id, "ligand_artifact_id": ligand_id, **tool_params},
                require_approval=False,
            )
        result = self._submit_pipeline_hpc_step(session=session, task=task, invocation=invocation, handoff=handoff, operation_key=operation_key)
        self._record_pipeline_completed_operation(invocation, operation_key, result)
        self._emit(
            "execution.pipeline.step.completed",
            {
                "invocation_id": invocation.invocation_id,
                "operation": method,
                "operation_key": operation_key,
                "run_id": result.get("run_id"),
            },
        )
        return result

    def _pipeline_hpc_covered_by_approved_plan(
        self,
        *,
        pipeline: dict[str, Any],
        method: str,
        params: dict[str, Any],
    ) -> bool:
        plan = dict(pipeline.get("execution_plan") or {})
        if not plan or pipeline.get("approved_plan_digest") != plan.get("plan_digest"):
            return False
        input_ids = {str(value) for value in list((pipeline.get("inputs") or {}).get("artifact_ids") or [])}
        input_ids.update(str(value) for value in list((pipeline.get("inputs") or {}).get("context_artifact_ids") or []))
        requested_artifact_ids = self._pipeline_hpc_artifact_ids(method, params)
        if not requested_artifact_ids.issubset(input_ids | set(pipeline.get("preprocess_artifact_ids") or [])):
            return False
        for operation in list(plan.get("hpc_operations") or []):
            if operation.get("method") != method:
                continue
            planned_ids = {str(value) for value in list(operation.get("artifact_ids") or [])}
            if planned_ids and not requested_artifact_ids.issubset(planned_ids | set(pipeline.get("preprocess_artifact_ids") or [])):
                continue
            return True
        return False

    def _pipeline_hpc_artifact_ids(self, method: str, params: dict[str, Any]) -> set[str]:
        if method == "hpc.fpocket":
            return {str(params["structure_artifact_id"])}
        if method == "hpc.vina":
            return {str(params["receptor_artifact_id"]), str(params["ligand_artifact_id"])}
        return set()

    def _submit_pipeline_hpc_step(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        handoff: ExecutionHandoff,
        operation_key: str,
    ) -> dict[str, Any]:
        required_artifacts = self._resolve_artifacts(session.session_id, handoff.required_artifact_ids)
        context_artifacts = self._resolve_artifacts(session.session_id, handoff.context_artifact_ids)
        compiler = self.compiler or DefaultExecutionRequestCompiler()
        request = compiler.compile_request(
            handoff=handoff,
            task=task,
            resolved_required_artifacts=required_artifacts,
            resolved_context_artifacts=context_artifacts,
        )
        runspec = dict(request.get("runspec") or {})
        metadata = dict(runspec.get("metadata") or {})
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        metadata.update(
            {
                "pipeline_invocation_id": invocation.invocation_id,
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "pipeline_step_id": operation_key,
                "sandbox_status": "running",
            }
        )
        runspec["metadata"] = metadata
        request = dict(request)
        request["runspec"] = runspec
        self._validate_compiled_runspec_inputs(request=request, allowed_artifacts=(*required_artifacts, *context_artifacts))
        outcome = self.runner.submit_execution(session.session_id, request)
        now = utc_now_iso()
        run = RunRecord(
            run_id=f"run_{invocation.invocation_id}_{len(self.repositories.runs.list_by_invocation(session.session_id, invocation.invocation_id)) + 1}",
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            approval_id=invocation.approval_id,
            engine_name=invocation.engine_name,
            runner_run_id=outcome.job_id or outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            summary=None,
            created_at=now,
            updated_at=now,
            finished_at=now if outcome.status.is_terminal else None,
        )
        self.repositories.runs.save(run)
        artifact_records: tuple[SessionArtifactRecord, ...] = ()
        final_outcome = outcome
        if outcome.status is RunStatus.SUCCEEDED and not outcome.artifacts:
            final_outcome = self.runner.fetch_execution_artifacts(
                run_id=outcome.job_id or outcome.run_id,
                remote_run_dir=outcome.remote_run_dir,
                runspec=runspec,
                job_id=outcome.job_id,
            )
            self._emit(
                "execution.artifacts.fetched",
                {
                    "invocation_id": invocation.invocation_id,
                    "run_id": run.run_id,
                    "runner_run_id": run.runner_run_id,
                    "artifact_count": len(final_outcome.artifacts),
                    "relative_paths": [artifact.relative_path for artifact in final_outcome.artifacts],
                },
            )
        if final_outcome.status.is_terminal:
            artifact_records = self._persist_artifacts(
                session_id=session.session_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                invocation_id=invocation.invocation_id,
                run_id=run.run_id,
                runner_run_id=run.runner_run_id,
                created_at=now,
                artifacts=final_outcome.artifacts,
                request_metadata=metadata,
                expected_outputs=tuple(dict(item) for item in list(runspec.get("expected_outputs") or [])),
            )
            run = RunRecord(
                run_id=run.run_id,
                session_id=run.session_id,
                task_id=run.task_id,
                lane_id=run.lane_id,
                invocation_id=run.invocation_id,
                approval_id=run.approval_id,
                engine_name=run.engine_name,
                runner_run_id=run.runner_run_id,
                status=final_outcome.status,
                execution_mode=run.execution_mode,
                remote_run_dir=run.remote_run_dir,
                summary=f"{handoff.catalog_tool_id} pipeline step {final_outcome.status.value}",
                created_at=run.created_at,
                updated_at=utc_now_iso(),
                finished_at=utc_now_iso(),
            )
            self.repositories.runs.save(run)
        parsed_result = None
        if final_outcome.status is RunStatus.SUCCEEDED:
            parser = self.parser or DefaultExecutionResultParser()
            parsed_result = parser.parse_result(
                handoff=handoff,
                outcome=final_outcome,
                artifact_refs=artifact_records,
            )
        return {
            "tool_id": handoff.catalog_tool_id,
            "run_id": run.run_id,
            "runner_run_id": run.runner_run_id,
            "status": run.status.value,
            "execution_mode": run.execution_mode,
            "exit_code": final_outcome.exit_code,
            "error_code": final_outcome.raw_result.get("error_code"),
            "stage": final_outcome.raw_result.get("stage"),
            "raw_result": final_outcome.raw_result,
            "parsed_result": None if parsed_result is None else parsed_result.to_dict(),
            "runner_result": {
                "status": final_outcome.raw_result.get("status"),
                "exit_code": final_outcome.raw_result.get("exit_code"),
                "error_code": final_outcome.raw_result.get("error_code"),
                "stage": final_outcome.raw_result.get("stage"),
                "stdout": final_outcome.raw_result.get("stdout"),
                "stderr": final_outcome.raw_result.get("stderr"),
                "logs": final_outcome.raw_result.get("logs"),
            },
            "artifacts": [project_artifact_for_agent(artifact) for artifact in artifact_records],
        }

    def _run_pipeline_preprocess(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = self.preprocess_adapter or DefaultPreprocessAdapter()
        if method == "preprocess.smiles_to_3d":
            smiles = str(params["smiles"]).strip()
            title = _safe_ref(str(params.get("title") or "ligand"))
            source_path = Path(tempfile.gettempdir()) / "openzyme-preprocess" / session.session_id / invocation.invocation_id / f"{title}.smi"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(smiles + "\n", encoding="utf-8")
            source = SessionArtifactRecord(
                artifact_id=f"pipeline_smiles_{hashlib.sha256(smiles.encode('utf-8')).hexdigest()[:12]}",
                session_id=session.session_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                invocation_id=invocation.invocation_id,
                run_id=None,
                kind=ArtifactKind.STRUCTURE,
                storage_uri=str(source_path),
                relative_path=f"preprocess/{invocation.invocation_id}/{title}.smi",
                title=f"{title}.smi",
                description="SMILES input generated inside execution pipeline.",
                metadata={"format": "smiles", "smiles": smiles, "source": "pipeline"},
                created_at=utc_now_iso(),
            )
            self.repositories.artifacts.save(source)
            draft = adapter._prepare_artifact(  # type: ignore[attr-defined]
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                slot_name=title,
                artifact=source,
                operation="prepare_ligand",
            )
        else:
            artifact = self.repositories.artifacts.get(str(params["artifact_id"]))
            if artifact is None or artifact.session_id != session.session_id:
                raise ValueError(f"artifact {params.get('artifact_id')!r} is not available in this session")
            if method == "preprocess.prepare_receptor":
                slot_name = "receptor"
                operation = "prepare_receptor"
            elif method == "preprocess.prepare_ligand":
                slot_name = "ligand"
                operation = "prepare_ligand"
            else:
                slot_name = _safe_ref(str(PurePosixPath(artifact.relative_path).stem or artifact.artifact_id))
                operation = "convert_format"
            if operation == "convert_format":
                output_format = str(params.get("output_format") or "pdbqt").lower()
                if output_format != "pdbqt":
                    raise ValueError("pipeline preprocess.convert_format currently supports output_format='pdbqt'")
                operation = "prepare_ligand"
            draft = adapter._prepare_artifact(  # type: ignore[attr-defined]
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                slot_name=slot_name,
                artifact=artifact,
                operation=operation,
            )
        records = self._persist_preprocess_artifacts(
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            drafts=(draft,),
        )
        record = records[0]
        self._emit(
            "execution.preprocess.completed",
            {
                "invocation_id": invocation.invocation_id,
                "artifact_ids": [record.artifact_id],
                "source_artifact_ids": [draft.source_artifact_id],
            },
        )
        self._append_pipeline_list(invocation, "preprocess_artifact_ids", [record.artifact_id])
        return self._sandbox_safe_artifact(record)

    def _request_pipeline_approval(
        self,
        *,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
        operation_key: str,
    ) -> ApprovalRequest:
        existing = self._load_approval(invocation)
        if existing is not None and existing.status is ApprovalRequestStatus.PENDING:
            return existing
        now = utc_now_iso()
        approval_id = f"appr_{uuid4().hex[:12]}"
        approval = ApprovalRequest(
            approval_id=approval_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            kind="execution_pipeline_operation",
            requested_action=f"Approve SDK operation {method} for pipeline invocation {invocation.invocation_id}",
            status=ApprovalRequestStatus.PENDING,
            request_ref=f"artifact://approvals/{approval_id}.json",
            resolution_ref=None,
            created_at=now,
        )
        self.repositories.approvals.save(approval)
        waiting = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.WAITING_APPROVAL,
            input_ref=invocation.input_ref,
            output_ref=invocation.output_ref,
            approval_id=approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=None,
        )
        self.repositories.invocations.save(waiting)
        self._update_pipeline_document(
            invocation,
            {
                "pending_operation": {
                    "operation_key": operation_key,
                    "method": method,
                    "params": params,
                    "approval_id": approval_id,
                    "requested_at": now,
                },
                "sandbox_status": "waiting_approval",
            },
        )
        self._emit(
            "approval.requested",
            {
                "approval_id": approval.approval_id,
                "task_id": approval.task_id,
                "lane_id": approval.lane_id,
                "kind": approval.kind,
            },
        )
        return approval

    def _record_pipeline_approval_resolution(
        self,
        invocation: EngineInvocation,
        approval: ApprovalRequest | None,
        resolution: str | None,
    ) -> None:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        pending = dict(pipeline.get("pending_operation") or {})
        updates: dict[str, Any] = {"resolution": resolution}
        if approval is not None and approval.status is ApprovalRequestStatus.APPROVED:
            if approval.kind == "execution_pipeline_plan":
                plan = dict(pipeline.get("execution_plan") or {})
                if plan.get("plan_digest") != pipeline.get("plan_digest"):
                    raise ValueError("approved execution plan digest does not match the persisted pipeline plan")
                updates["approved_plan_digest"] = plan.get("plan_digest")
                updates["sandbox_status"] = "approved"
            elif pending.get("operation_key"):
                approved = list(pipeline.get("approved_operation_keys") or [])
                if str(pending["operation_key"]) not in approved:
                    approved.append(str(pending["operation_key"]))
                updates["approved_operation_keys"] = approved
                updates["pending_operation"] = None
                updates["sandbox_status"] = "approved"
        elif approval is not None and approval.status is not ApprovalRequestStatus.PENDING:
            updates["sandbox_status"] = approval.status.value
        self._update_pipeline_document(invocation, updates)

    def _record_pipeline_completed_operation(
        self,
        invocation: EngineInvocation,
        operation_key: str,
        result: dict[str, Any],
    ) -> None:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        completed = dict(pipeline.get("completed_operations") or {})
        completed[operation_key] = result
        hpc_run_ids = list(pipeline.get("hpc_run_ids") or [])
        if result.get("run_id") and str(result["run_id"]) not in hpc_run_ids:
            hpc_run_ids.append(str(result["run_id"]))
        self._update_pipeline_document(
            invocation,
            {
                "completed_operations": completed,
                "hpc_run_ids": hpc_run_ids,
                "sandbox_status": "running",
            },
        )

    def _finalize_pipeline_sdk_failure(
        self,
        *,
        invocation: EngineInvocation,
        failure: PipelineSdkFailure,
    ) -> ExecutionStartResult:
        now = utc_now_iso()
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        output_id = _new_document_id("eng_out")
        error_payload: dict[str, Any] = {
            "type": failure.error_type,
            "stage": failure.stage,
            "retryable": failure.retryable,
            "message": failure.message,
            "hint": failure.hint,
            "sdk_method": failure.sdk_method,
            "details": failure.details,
        }
        if failure.hpc_failure is not None:
            error_payload["hpc_failure"] = failure.hpc_failure
        payload = {
            "pipeline": {
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "sandbox_status": "failed",
                "terminal_summary": failure.message,
                "error": error_payload,
            }
        }
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_result",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )
        failed = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=invocation.input_ref,
            output_ref=output_id,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(failed)
        self._update_pipeline_document(invocation, {"sandbox_status": "failed"})
        self._emit(
            "execution.pipeline.failed",
            {"invocation_id": invocation.invocation_id, "error": error_payload},
        )
        return ExecutionStartResult(
            invocation=failed,
            run=None,
            approval=None,
            parsed_result=ExecutionParsedResult(
                result_summary=failure.message,
                structured_findings=payload["pipeline"],
            ),
        )

    def _finalize_pipeline_terminal(
        self,
        *,
        invocation: EngineInvocation,
        outcome: ExecutionOutcome,
    ) -> ExecutionStartResult:
        now = utc_now_iso()
        sandbox_run = RunRecord(
            run_id=f"run_{invocation.invocation_id}_sandbox",
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            approval_id=invocation.approval_id,
            engine_name=invocation.engine_name,
            runner_run_id=outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            summary="Pipeline sandbox completed." if outcome.status is RunStatus.SUCCEEDED else "Pipeline sandbox failed.",
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
        self.repositories.runs.save(sandbox_run)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        self._persist_artifacts(
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=sandbox_run.run_id,
            runner_run_id=sandbox_run.runner_run_id,
            created_at=now,
            artifacts=outcome.artifacts,
            request_metadata={
                "pipeline_invocation_id": invocation.invocation_id,
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "input_artifact_ids": list((pipeline.get("inputs") or {}).get("artifact_ids") or []),
                "preprocess_artifact_ids": list(pipeline.get("preprocess_artifact_ids") or []),
                "bio_artifact_ids": list(pipeline.get("bio_artifact_ids") or []),
                "tool_contract": {},
            },
        )
        output_id = _new_document_id("eng_out")
        stderr_excerpt = next(
            (
                _text_excerpt(artifact.storage_uri)
                for artifact in outcome.artifacts
                if artifact.relative_path == "logs/stderr.log"
            ),
            None,
        )
        stdout_excerpt = next(
            (
                _text_excerpt(artifact.storage_uri)
                for artifact in outcome.artifacts
                if artifact.relative_path == "logs/stdout.log"
            ),
            None,
        )
        failure_excerpt = stderr_excerpt or stdout_excerpt
        completed_operations = dict(pipeline.get("completed_operations") or {})
        successful_results = [
            result
            for result in completed_operations.values()
            if isinstance(result, dict) and result.get("status") == RunStatus.SUCCEEDED.value
        ]
        successful_parsed = [
            dict(parsed)
            for parsed in (
                result.get("parsed_result")
                for result in successful_results
                if isinstance(result, dict)
            )
            if isinstance(parsed, dict)
        ]
        if outcome.status is RunStatus.SUCCEEDED and successful_parsed:
            summary = str(
                successful_parsed[-1].get("result_summary")
                or "Pipeline sandbox completed."
            )
        elif outcome.status is RunStatus.SUCCEEDED:
            summary = "Pipeline sandbox completed."
        elif failure_excerpt:
            first_line = failure_excerpt.splitlines()[0]
            summary = f"Pipeline failed: {first_line}"
        else:
            summary = "Pipeline failed."
        error_type = "sandbox_execution_failed"
        error_hint = "Read the log excerpts, correct the pipeline code, and retry execution.pipeline.start with declared inputs."
        hpc_failure = None
        if failure_excerpt and "PipelineSdkError: hpc." in failure_excerpt and " failed with status failed" in failure_excerpt:
            error_type = "hpc_operation_failed"
            error_hint = (
                "The pipeline code reached the approved HPC operation, but the HPC runner returned failed. "
                "Do not retry with equivalent pipeline code; inspect the HPC run or runner configuration."
            )
            for completed_result in dict(pipeline.get("completed_operations") or {}).values():
                if isinstance(completed_result, dict):
                    hpc_failure = _hpc_failure_details(completed_result)
                    if hpc_failure is not None:
                        break
            if hpc_failure is not None and str(hpc_failure.get("error_code") or "").lower() in {
                "timeout",
                "command_timeout",
                "hpc_runner_timeout",
                "ssh_timeout",
            }:
                error_type = "hpc_runner_timeout"
                error_hint = (
                    "The Host-supervised HPC SDK call timed out while waiting on the runner or remote SSH/HPC boundary. "
                    "Treat this as an HPC runner timeout, not a Podman sandbox startup failure."
                )
        error_payload = None
        if outcome.status is not RunStatus.SUCCEEDED:
            error_payload = {
                "type": error_type,
                "stage": None if hpc_failure is None else hpc_failure.get("stage"),
                "retryable": error_type == "hpc_runner_timeout",
                "message": summary,
                "stderr_excerpt": stderr_excerpt,
                "stdout_excerpt": stdout_excerpt,
                "hint": error_hint,
                "sdk_method": "hpc.fpocket" if "hpc.fpocket" in (failure_excerpt or "") else None,
            }
            if hpc_failure is not None:
                error_payload["hpc_failure"] = hpc_failure
        all_artifacts = self.repositories.artifacts.list_by_invocation(
            invocation.session_id, invocation.invocation_id
        )
        output_payload = {
            "pipeline": {
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "sandbox_status": outcome.status.value,
                "hpc_run_ids": list(pipeline.get("hpc_run_ids") or []),
                "input_artifact_ids": list((pipeline.get("inputs") or {}).get("artifact_ids") or []),
                "preprocess_artifact_ids": list(pipeline.get("preprocess_artifact_ids") or []),
                "bio_artifact_ids": list(pipeline.get("bio_artifact_ids") or []),
                "completed_operations": completed_operations,
                "output_artifact_ids": [artifact.artifact_id for artifact in all_artifacts],
                "terminal_summary": summary,
                "parsed_result": None if not successful_parsed else successful_parsed[-1],
                "error": error_payload,
            },
            "sandbox_outcome": {
                "run_id": outcome.run_id,
                "status": outcome.status.value,
                "execution_mode": outcome.execution_mode,
                "remote_run_dir": outcome.remote_run_dir,
                "exit_code": outcome.exit_code,
                "raw_result": outcome.raw_result,
            },
            "runs": [
                run.to_dict()
                for run in self.repositories.runs.list_by_invocation(
                    invocation.session_id, invocation.invocation_id
                )
            ],
            "artifacts": [project_artifact_for_agent(artifact) for artifact in all_artifacts],
        }
        output_payload = sanitize_private_artifact_fields(output_payload)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_result",
                payload=output_payload,
                created_at=now,
                updated_at=now,
            )
        )
        status = EngineInvocationStatus.SUCCEEDED if outcome.status is RunStatus.SUCCEEDED else EngineInvocationStatus.FAILED
        finalized = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=status,
            input_ref=invocation.input_ref,
            output_ref=output_id,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(finalized)
        self._update_pipeline_document(invocation, {"sandbox_status": outcome.status.value})
        self._emit(
            "execution.pipeline.completed" if outcome.status is RunStatus.SUCCEEDED else "execution.pipeline.failed",
            {"invocation_id": invocation.invocation_id, "status": status.value},
        )
        self._emit(
            "engine.invocation.completed",
            {"invocation_id": finalized.invocation_id, "engine_name": finalized.engine_name, "status": finalized.status.value},
        )
        parsed = ExecutionParsedResult(
            result_summary=summary,
            structured_findings=output_payload["pipeline"],
        )
        return ExecutionStartResult(
            invocation=finalized,
            run=sandbox_run,
            approval=self._load_approval(finalized),
            artifacts=tuple(all_artifacts),
            parsed_result=parsed,
        )

    def _submit_execution(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        handoff: ExecutionHandoff,
    ) -> ExecutionStartResult:
        required_artifacts = self._resolve_artifacts(session.session_id, handoff.required_artifact_ids)
        context_artifacts = self._resolve_artifacts(session.session_id, handoff.context_artifact_ids)
        preprocessor = self.preprocess_adapter or DefaultPreprocessAdapter()
        preprocess_result = preprocessor.preprocess_for_execution(
            session_id=session.session_id,
            invocation_id=invocation.invocation_id,
            handoff=handoff,
            required_artifacts=required_artifacts,
        )
        preprocess_artifacts = self._persist_preprocess_artifacts(
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            drafts=preprocess_result.created_artifacts,
        )
        if preprocess_artifacts:
            by_source = {
                str(artifact.metadata.get("source_artifact_id")): artifact
                for artifact in preprocess_artifacts
                if artifact.metadata
            }
            required_artifacts = tuple(
                by_source.get(artifact.artifact_id, artifact)
                for artifact in required_artifacts
            )
            self._emit(
                "execution.preprocess.completed",
                {
                    "invocation_id": invocation.invocation_id,
                    "artifact_ids": [artifact.artifact_id for artifact in preprocess_artifacts],
                    "source_artifact_ids": list(by_source),
                },
            )
        else:
            required_artifacts = preprocess_result.required_artifacts
        compiler = self.compiler or DefaultExecutionRequestCompiler()
        request = compiler.compile_request(
            handoff=handoff,
            task=task,
            resolved_required_artifacts=required_artifacts,
            resolved_context_artifacts=context_artifacts,
        )
        self._validate_compiled_runspec_inputs(
            request=request,
            allowed_artifacts=(*required_artifacts, *context_artifacts),
        )
        pipeline = dict((self._require_input_payload(invocation).get("pipeline") or {}))
        if pipeline:
            metadata = dict((request.get("runspec") or {}).get("metadata") or {})
            metadata.update(
                {
                    "pipeline_invocation_id": invocation.invocation_id,
                    "code_digest": pipeline.get("code_digest"),
                    "sdk_operation_log": list(pipeline.get("sdk_operation_log") or []),
                }
            )
            request = dict(request)
            runspec = dict(request.get("runspec") or {})
            runspec["metadata"] = metadata
            request["runspec"] = runspec
        self._update_input_document(invocation, request=request)
        outcome = self.runner.submit_execution(session.session_id, request)
        now = utc_now_iso()
        run = RunRecord(
            run_id=f"run_{invocation.invocation_id}",
            session_id=session.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            approval_id=invocation.approval_id,
            engine_name=invocation.engine_name,
            runner_run_id=outcome.job_id or outcome.run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            summary=None,
            created_at=now,
            updated_at=now,
            finished_at=now if outcome.status.is_terminal else None,
        )
        self.repositories.runs.save(run)
        if outcome.status.is_terminal:
            return self._finalize_terminal(invocation=invocation, run=run, handoff=handoff, outcome=outcome)
        running = self._replace_invocation(invocation, status=EngineInvocationStatus.RUNNING, finished_at=None)
        self.repositories.invocations.save(running)
        self._emit(
            "engine.invocation.updated",
            {"invocation_id": running.invocation_id, "engine_name": running.engine_name, "status": "running"},
        )
        return ExecutionStartResult(invocation=running, run=run, approval=None)

    def _validate_compiled_runspec_inputs(
        self,
        *,
        request: dict[str, Any],
        allowed_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> None:
        runspec = dict(request.get("runspec") or {})
        allowed_by_id = {artifact.artifact_id: artifact for artifact in allowed_artifacts}
        allowed_paths = {artifact.storage_uri: artifact.artifact_id for artifact in allowed_artifacts}
        for item in list(runspec.get("inputs") or []):
            if not isinstance(item, dict):
                raise ValueError("runspec inputs must be objects")
            artifact_id = item.get("artifact_id")
            local_path = str(item.get("local_path") or "")
            if not artifact_id:
                raise ValueError("runspec inputs must include artifact_id")
            artifact = allowed_by_id.get(str(artifact_id))
            if artifact is None:
                raise ValueError(f"runspec input artifact_id {artifact_id!r} is not a resolved session artifact")
            if artifact.storage_uri != local_path:
                expected_id = allowed_paths.get(local_path)
                if expected_id is None:
                    raise ValueError(f"runspec input local_path {local_path!r} is not a resolved session artifact")
                raise ValueError(
                    f"runspec input local_path {local_path!r} belongs to artifact {expected_id!r}, not {artifact_id!r}"
                )

    def _finalize_terminal(
        self,
        *,
        invocation: EngineInvocation,
        run: RunRecord,
        handoff: ExecutionHandoff,
        outcome: ExecutionOutcome,
    ) -> ExecutionStartResult:
        now = utc_now_iso()
        request_runspec = dict((self._require_input_payload(invocation).get("request") or {}).get("runspec") or {})
        artifacts = self._persist_artifacts(
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=run.run_id,
            created_at=now,
            artifacts=outcome.artifacts,
            runner_run_id=run.runner_run_id,
            request_metadata=dict(request_runspec.get("metadata") or {}),
            expected_outputs=tuple(dict(item) for item in list(request_runspec.get("expected_outputs") or [])),
        )
        parser = self.parser or DefaultExecutionResultParser()
        parsed_result = parser.parse_result(handoff=handoff, outcome=outcome, artifact_refs=artifacts)
        output_id = _new_document_id("eng_out")
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_result",
                payload={
                    "run": run.to_dict(),
                    "outcome": {
                        "run_id": outcome.run_id,
                        "status": outcome.status.value,
                        "execution_mode": outcome.execution_mode,
                        "remote_run_dir": outcome.remote_run_dir,
                        "job_id": outcome.job_id,
                        "exit_code": outcome.exit_code,
                        "artifacts": [artifact.to_dict() for artifact in outcome.artifacts],
                        "raw_result": outcome.raw_result,
                    },
                    "parsed_result": parsed_result.to_dict(),
                },
                created_at=now,
                updated_at=now,
            )
        )
        updated_run = RunRecord(
            run_id=run.run_id,
            session_id=run.session_id,
            task_id=run.task_id,
            lane_id=run.lane_id,
            invocation_id=run.invocation_id,
            approval_id=run.approval_id,
            engine_name=run.engine_name,
            runner_run_id=run.runner_run_id,
            status=outcome.status,
            execution_mode=outcome.execution_mode,
            remote_run_dir=outcome.remote_run_dir,
            summary=parsed_result.result_summary,
            created_at=run.created_at,
            updated_at=now,
            finished_at=now,
        )
        self.repositories.runs.save(updated_run)
        finalized_invocation = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=_invocation_status_from_run(outcome.status),
            input_ref=invocation.input_ref,
            output_ref=output_id,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(finalized_invocation)
        self.repositories.memory.save(
            MemoryEntry(
                memory_id=f"mem_{uuid4().hex[:12]}",
                session_id=invocation.session_id,
                scope_kind=MemoryScopeKind.TASK,
                scope_ref=str(invocation.task_id or invocation.session_id),
                kind=MemoryKind.SUMMARY,
                summary=parsed_result.result_summary,
                source_range=f"engine:{invocation.invocation_id}",
                importance=6,
                created_at=now,
            )
        )
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": finalized_invocation.invocation_id,
                "engine_name": finalized_invocation.engine_name,
                "status": finalized_invocation.status.value,
            },
        )
        return ExecutionStartResult(
            invocation=finalized_invocation,
            run=updated_run,
            approval=None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id),
            artifacts=artifacts,
            parsed_result=parsed_result,
        )

    def _persist_artifacts(
        self,
        *,
        session_id: str,
        task_id: str | None,
        lane_id: str | None,
        invocation_id: str,
        run_id: str,
        runner_run_id: str,
        created_at: str,
        artifacts: tuple[ExecutionArtifactRef, ...],
        request_metadata: dict[str, Any],
        expected_outputs: tuple[dict[str, Any], ...] = (),
    ) -> tuple[SessionArtifactRecord, ...]:
        persisted: list[SessionArtifactRecord] = []
        input_artifact_ids = list(request_metadata.get("input_artifact_ids") or request_metadata.get("required_artifact_ids") or [])
        preprocess_artifact_ids = list(request_metadata.get("preprocess_artifact_ids") or [])
        bio_artifact_ids = list(request_metadata.get("bio_artifact_ids") or [])
        tool_contract = dict(request_metadata.get("tool_contract") or {})
        declared_paths = {str(item.get("path")) for item in expected_outputs}
        for artifact in artifacts:
            if declared_paths and artifact.relative_path not in declared_paths:
                continue
            artifact_id = f"{run_id}:{_safe_ref(artifact.relative_path)}"
            record = SessionArtifactRecord(
                artifact_id=artifact_id,
                session_id=session_id,
                task_id=task_id,
                lane_id=lane_id,
                invocation_id=invocation_id,
                run_id=run_id,
                kind=artifact.kind,
                storage_uri=artifact.storage_uri,
                relative_path=artifact.relative_path,
                title=PurePosixPath(artifact.relative_path).name,
                description=None,
                metadata={
                    "source": "execution_engine",
                    "runner_run_id": runner_run_id,
                    "remote_path": artifact.relative_path,
                    "expected_output_path": artifact.relative_path,
                    "tool_contract": tool_contract,
                    "pipeline_invocation_id": invocation_id,
                    "code_digest": request_metadata.get("code_digest"),
                    "source_code_artifact_id": request_metadata.get("source_code_artifact_id"),
                    "source_code_digest": request_metadata.get("source_code_digest"),
                    "source_code_version": request_metadata.get("source_code_version"),
                    "pipeline_step_id": request_metadata.get("pipeline_step_id"),
                    "input_artifact_ids": input_artifact_ids,
                    "preprocess_artifact_ids": preprocess_artifact_ids,
                    "bio_artifact_ids": bio_artifact_ids,
                },
                created_at=created_at,
            )
            self.repositories.artifacts.save(record)
            self._emit(
                "artifact.recorded",
                {
                    "artifact_id": record.artifact_id,
                    "session_id": record.session_id,
                    "run_id": record.run_id,
                    "relative_path": record.relative_path,
                },
            )
            persisted.append(record)
        return tuple(persisted)

    def _persist_preprocess_artifacts(
        self,
        *,
        session_id: str,
        task_id: str | None,
        lane_id: str | None,
        invocation_id: str,
        drafts: tuple[PreprocessArtifactDraft, ...],
    ) -> tuple[SessionArtifactRecord, ...]:
        persisted: list[SessionArtifactRecord] = []
        now = utc_now_iso()
        for draft in drafts:
            record = SessionArtifactRecord(
                artifact_id=f"{draft.source_artifact_id}:preprocess:{_safe_ref(draft.relative_path)}",
                session_id=session_id,
                task_id=task_id,
                lane_id=lane_id,
                invocation_id=invocation_id,
                run_id=None,
                kind=ArtifactKind.STRUCTURE,
                storage_uri=draft.storage_uri,
                relative_path=draft.relative_path,
                title=PurePosixPath(draft.relative_path).name,
                description=f"{draft.operation} output for {draft.source_artifact_id}",
                metadata={
                    "source": "preprocess",
                    "pipeline_invocation_id": invocation_id,
                    "code_digest": draft.metadata.get("code_digest"),
                    "source_artifact_id": draft.source_artifact_id,
                    "operation": draft.operation,
                    "input_format": draft.input_format,
                    "output_format": draft.output_format,
                    "tool": draft.tool,
                    "provenance": draft.metadata,
                },
                created_at=now,
            )
            self.repositories.artifacts.save(record)
            persisted.append(record)
        return tuple(persisted)

    def _persist_bio_artifacts(
        self,
        *,
        session_id: str,
        task_id: str | None,
        lane_id: str | None,
        invocation_id: str,
        operation_key: str,
        drafts: tuple[BioArtifactDraft, ...],
        request_metadata: dict[str, Any],
    ) -> tuple[SessionArtifactRecord, ...]:
        persisted: list[SessionArtifactRecord] = []
        now = utc_now_iso()
        base_dir = Path(tempfile.gettempdir()) / "openzyme-bio" / _safe_ref(session_id) / _safe_ref(invocation_id)
        for draft in drafts:
            relative = PurePosixPath(draft.relative_path)
            relative_path = relative.as_posix()
            if relative.is_absolute() or not relative_path or any(part in {"", ".", ".."} for part in relative.parts):
                raise PipelineSdkFailure(
                    error_type="invalid_bio_artifact_path",
                    message=f"Bio SDK generated invalid artifact path {draft.relative_path!r}.",
                    hint="Retry after fixing the Host bio provider adapter.",
                    stage="bio_artifact_registration",
                    retryable=False,
                    sdk_method=request_metadata.get("sdk_method"),
                )
            storage_path = base_dir / relative_path
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path.write_text(draft.content, encoding="utf-8")
            record = SessionArtifactRecord(
                artifact_id=f"{invocation_id}:{operation_key}:{_safe_ref(relative_path)}",
                session_id=session_id,
                task_id=task_id,
                lane_id=lane_id,
                invocation_id=invocation_id,
                run_id=None,
                kind=draft.kind,
                storage_uri=str(storage_path),
                relative_path=relative_path,
                title=draft.title,
                description=f"Host-supervised bio SDK output for {operation_key}",
                metadata={
                    **draft.metadata,
                    "pipeline_invocation_id": invocation_id,
                    "sdk_method": request_metadata.get("sdk_method"),
                    "code_digest": request_metadata.get("code_digest"),
                    "source_code_artifact_id": request_metadata.get("source_code_artifact_id"),
                    "source_code_digest": request_metadata.get("source_code_digest"),
                    "source_code_version": request_metadata.get("source_code_version"),
                    "pipeline_step_id": operation_key,
                    "input_artifact_ids": list(request_metadata.get("input_artifact_ids") or []),
                    "preprocess_artifact_ids": list(request_metadata.get("preprocess_artifact_ids") or []),
                    "content_digest": f"sha256:{hashlib.sha256(draft.content.encode('utf-8')).hexdigest()}",
                },
                created_at=now,
            )
            self.repositories.artifacts.save(record)
            self._emit(
                "artifact.recorded",
                {
                    "artifact_id": record.artifact_id,
                    "session_id": record.session_id,
                    "relative_path": record.relative_path,
                    "source": "host_supervised_bio_sdk",
                },
            )
            persisted.append(record)
        return tuple(persisted)

    def _resolve_artifacts(self, session_id: str, artifact_ids: tuple[str, ...]) -> tuple[SessionArtifactRecord, ...]:
        resolved: list[SessionArtifactRecord] = []
        for artifact_id in artifact_ids:
            artifact = self.repositories.artifacts.get(artifact_id)
            if artifact is None:
                raise ValueError(f"artifact {artifact_id!r} does not exist")
            if artifact.session_id != session_id:
                raise ValueError(f"artifact {artifact_id!r} belongs to session {artifact.session_id!r}, not {session_id!r}")
            resolved.append(artifact)
        return tuple(resolved)

    def _require_pipeline_artifact(
        self,
        *,
        session_id: str,
        artifact_id: str,
        sdk_method: str,
    ) -> SessionArtifactRecord:
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None or artifact.session_id != session_id:
            raise PipelineSdkFailure(
                error_type="artifact_not_available",
                message=f"Artifact {artifact_id!r} is not available in this session.",
                hint="Pass an artifact id from the current session artifact catalog.",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"artifact_id": artifact_id},
            )
        return artifact

    def _require_run(self, invocation: EngineInvocation) -> RunRecord:
        run = self.repositories.runs.get_by_invocation(invocation.session_id, invocation.invocation_id)
        if run is None:
            raise ValueError(f"invocation {invocation.invocation_id!r} does not have a persisted run")
        return run

    def _load_approval(self, invocation: EngineInvocation) -> ApprovalRequest | None:
        return None if invocation.approval_id is None else self.repositories.approvals.get(invocation.approval_id)

    def _load_handoff(self, invocation: EngineInvocation) -> ExecutionHandoff:
        input_payload = self._require_input_payload(invocation)
        return ExecutionHandoff.from_payload(dict(input_payload["handoff"]))

    def _require_session(self, session_id: str) -> Any:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        return session

    def _require_task(self, session_id: str, task_id: str) -> Any:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        if task.session_id != session_id:
            raise ValueError(f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}")
        return task

    def _require_invocation(self, invocation_id: str) -> EngineInvocation:
        invocation = self.repositories.invocations.get(invocation_id)
        if invocation is None:
            raise ValueError(f"invocation {invocation_id!r} does not exist")
        return invocation

    def _require_input_payload(self, invocation: EngineInvocation) -> dict[str, Any]:
        if invocation.input_ref is None:
            raise ValueError(f"invocation {invocation.invocation_id!r} does not have an input document")
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            raise ValueError(f"input document {invocation.input_ref!r} does not exist")
        return document.payload

    def _update_input_document(
        self,
        invocation: EngineInvocation,
        *,
        request: dict[str, Any] | None = None,
        resolution: str | None = None,
        pipeline: dict[str, Any] | None = None,
    ) -> None:
        if invocation.input_ref is None:
            return
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            return
        payload = dict(document.payload)
        if request is not None:
            payload["request"] = request
        if resolution is not None:
            payload["resolution"] = resolution
        if pipeline is not None:
            payload["pipeline"] = pipeline
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=document.document_id,
                session_id=document.session_id,
                invocation_id=str(document.invocation_id),
                document_kind=document.document_kind,
                payload=payload,
                created_at=document.created_at,
                updated_at=utc_now_iso(),
            )
        )

    def _update_pipeline_document(self, invocation: EngineInvocation, updates: dict[str, Any]) -> None:
        if invocation.input_ref is None:
            return
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            return
        payload = dict(document.payload)
        pipeline = dict(payload.get("pipeline") or {})
        for key, value in updates.items():
            if value is None:
                pipeline.pop(key, None)
            else:
                pipeline[key] = value
        payload["pipeline"] = pipeline
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=document.document_id,
                session_id=document.session_id,
                invocation_id=str(document.invocation_id),
                document_kind=document.document_kind,
                payload=payload,
                created_at=document.created_at,
                updated_at=utc_now_iso(),
            )
        )

    def _append_pipeline_list(self, invocation: EngineInvocation, key: str, values: list[str]) -> None:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        current = list(pipeline.get(key) or [])
        for value in values:
            if value not in current:
                current.append(value)
        self._update_pipeline_document(invocation, {key: current})

    def _pipeline_operation_key(self, method: str, params: dict[str, Any]) -> str:
        canonical = json.dumps({"method": method, "params": params}, sort_keys=True, separators=(",", ":"))
        return f"{method}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"

    def _require_pdbqt_artifact(self, artifact_id: str, *, slot_name: str) -> None:
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None:
            raise ValueError(f"{slot_name} artifact {artifact_id!r} does not exist")
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if metadata_format == "pdbqt" or artifact.storage_uri.lower().endswith(".pdbqt") or artifact.relative_path.lower().endswith(".pdbqt"):
            return
        raise ValueError(f"{slot_name} artifact {artifact_id!r} must be PDBQT; use preprocess.prepare_receptor/prepare_ligand first")

    def _validate_fpocket_artifact(self, artifact_id: str) -> None:
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None:
            raise PipelineSdkFailure(
                error_type="invalid_fpocket_input",
                message=f"fpocket structure artifact {artifact_id!r} does not exist.",
                hint="Provide an existing PDB artifact before calling hpc.fpocket.",
                stage="input_validation",
                retryable=False,
                sdk_method="hpc.fpocket",
            )
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        is_pdb = metadata_format == "pdb" or artifact.storage_uri.lower().endswith(".pdb") or artifact.relative_path.lower().endswith(".pdb")
        if not is_pdb:
            raise PipelineSdkFailure(
                error_type="invalid_fpocket_input",
                message=f"fpocket structure artifact {artifact_id!r} must be a PDB file or declare metadata format=pdb.",
                hint="Use a valid PDB artifact for fpocket; convert or replace non-PDB structures before requesting HPC approval.",
                stage="input_validation",
                retryable=False,
                sdk_method="hpc.fpocket",
            )
        atom_count, residue_count = _count_pdb_atoms_and_residues(artifact.storage_uri)
        if atom_count < 50 or residue_count < 10:
            raise PipelineSdkFailure(
                error_type="invalid_fpocket_input",
                message=(
                    f"fpocket structure artifact {artifact_id!r} is too small for fpocket "
                    f"({atom_count} ATOM/HETATM records, {residue_count} residues)."
                ),
                hint="Use a protein-scale PDB with at least 50 ATOM/HETATM records and at least 10 residues.",
                stage="input_validation",
                retryable=False,
                sdk_method="hpc.fpocket",
            )

    def _sandbox_safe_artifact(self, artifact: SessionArtifactRecord) -> dict[str, Any]:
        payload = project_artifact_for_agent(artifact)
        payload["path"] = None
        return payload

    def _replace_invocation(
        self,
        invocation: EngineInvocation,
        *,
        status: EngineInvocationStatus,
        finished_at: str | None,
    ) -> EngineInvocation:
        return EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=status,
            input_ref=invocation.input_ref,
            output_ref=invocation.output_ref,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=finished_at,
        )

    def _document_record(
        self,
        *,
        document_id: str,
        session_id: str,
        invocation_id: str,
        document_kind: str,
        payload: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> Any:
        from openzyme_core import EngineDocumentRecord

        return EngineDocumentRecord(
            document_id=document_id,
            session_id=session_id,
            invocation_id=invocation_id,
            document_kind=document_kind,
            payload=payload,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)

    def _dry_run_operation_log(self, code: str) -> list[dict[str, Any]]:
        doc_hints = {
            "bio.ncbi_fetch_proteins": ("bio.ncbi_fetch_proteins", "bio.md"),
            "bio.uniprot_fetch": ("bio.uniprot_fetch", "bio.md"),
            "bio.hmmer_search": ("bio.hmmer_search", "bio.md"),
            "bio_tools.cdhit": ("bio_tools.cdhit", "bio-tools.md"),
            "bio_tools.mafft": ("bio_tools.mafft", "bio-tools.md"),
            "bio_tools.hmmbuild": ("bio_tools.hmmbuild", "bio-tools.md"),
            "bio_tools.hmmalign": ("bio_tools.hmmalign", "bio-tools.md"),
            "bio_tools.hmmer_search_cli": ("bio_tools.hmmer_search_cli", "bio-tools.md"),
            "preprocess.convert_format": ("preprocess.convert_format", None),
            "preprocess.prepare_receptor": ("preprocess.prepare_receptor", None),
            "preprocess.prepare_ligand": ("preprocess.prepare_ligand", None),
            "preprocess.smiles_to_3d": ("preprocess.smiles_to_3d", None),
            "hpc.fpocket": ("hpc.fpocket", "hpc-fpocket.md"),
            "hpc.vina": ("hpc.vina", "hpc-vina.md"),
        }
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return [
                {
                    "operation": "parse_error",
                    "approval_required": False,
                    "error": exc.msg,
                    "hint": "Fix Python syntax before submitting execution.pipeline.start.",
                    "doc_keyword": "execution.pipeline.start",
                }
            ]
        operations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            owner = func.value
            if not isinstance(owner, ast.Name):
                continue
            operation = f"{owner.id}.{func.attr}"
            if operation not in {
                "artifacts.get",
                "artifacts.register",
                "artifacts.register_many",
                "bio.ncbi_fetch_proteins",
                "bio.uniprot_fetch",
                "bio.hmmer_search",
                "bio_tools.cdhit",
                "bio_tools.mafft",
                "bio_tools.hmmbuild",
                "bio_tools.hmmalign",
                "bio_tools.hmmer_search_cli",
                "preprocess.convert_format",
                "preprocess.prepare_receptor",
                "preprocess.prepare_ligand",
                "preprocess.smiles_to_3d",
                "hpc.fpocket",
                "hpc.vina",
                "run.wait",
                "run.fetch_artifacts",
            } or operation in seen:
                continue
            seen.add(operation)
            keyword, doc_id = doc_hints.get(operation, (operation, None))
            item: dict[str, Any] = {
                "operation": operation,
                "approval_required": operation.startswith("hpc."),
                "doc_keyword": keyword,
            }
            if doc_id is not None:
                item["doc_id"] = doc_id
            operations.append(item)
        return operations

    def _build_execution_plan(
        self,
        *,
        code: str,
        code_digest: str,
        inputs: dict[str, Any],
        source_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        operations = self._dry_run_operation_log(code)
        artifact_ids = [str(value) for value in list(inputs.get("artifact_ids") or [])]
        context_artifact_ids = [str(value) for value in list(inputs.get("context_artifact_ids") or [])]
        artifact_reads = [
            {"artifact_id": artifact_id, "scope": "required"}
            for artifact_id in artifact_ids
        ] + [
            {"artifact_id": artifact_id, "scope": "context"}
            for artifact_id in context_artifact_ids
        ]
        preprocess_operations = [
            {
                "method": item["operation"],
                "approval_required": False,
                "doc_keyword": item.get("doc_keyword"),
            }
            for item in operations
            if str(item.get("operation", "")).startswith("preprocess.")
        ]
        bio_operations = [
            {
                "method": str(item["operation"]),
                "provider": self._planned_bio_provider(str(item["operation"])),
                "approval_required": False,
                "expected_outputs": self._planned_bio_expected_outputs(str(item["operation"])),
                "quota_estimate": self._planned_bio_quota_estimate(str(item["operation"])),
                "doc_keyword": item.get("doc_keyword"),
                "doc_id": item.get("doc_id"),
            }
            for item in operations
            if str(item.get("operation", "")).startswith("bio.")
        ]
        bio_tool_operations = [
            {
                "method": str(item["operation"]),
                "approval_required": False,
                "expected_outputs": self._planned_bio_tool_expected_outputs(str(item["operation"])),
                "resource_estimate": self._planned_bio_tool_resource_estimate(str(item["operation"])),
                "quota_estimate": {"local_tool_invocations": 1, "operation": str(item["operation"])},
                "doc_keyword": item.get("doc_keyword"),
                "doc_id": item.get("doc_id"),
            }
            for item in operations
            if str(item.get("operation", "")).startswith("bio_tools.")
        ]
        hpc_operations: list[dict[str, Any]] = []
        all_input_ids = [*artifact_ids, *context_artifact_ids]
        for item in operations:
            method = str(item.get("operation") or "")
            if not method.startswith("hpc."):
                continue
            artifact_scope = all_input_ids[:1] if method == "hpc.fpocket" else all_input_ids[:2]
            hpc_operations.append(
                {
                    "method": method,
                    "operation_key": self._planned_pipeline_operation_key(method, artifact_scope),
                    "artifact_ids": artifact_scope,
                    "params": {"source": "static_dry_run", "runtime_params_must_match_policy": True},
                    "approval_required": True,
                    "expected_outputs": self._planned_expected_outputs(method),
                    "resource_estimate": self._planned_resource_estimate(method),
                    "quota_estimate": self._planned_quota_estimate(method),
                    "doc_keyword": item.get("doc_keyword"),
                    "doc_id": item.get("doc_id"),
                }
            )
        approval_requirements = [
            {
                "kind": "hpc_operation",
                "method": operation["method"],
                "operation_key": operation["operation_key"],
                "reason": "HPC execution is approval-gated by policy.",
            }
            for operation in hpc_operations
        ]
        plan_without_digest = {
            "code_digest": code_digest,
            **source_metadata,
            "artifact_reads": artifact_reads,
            "bio_operations": bio_operations,
            "bio_tool_operations": bio_tool_operations,
            "preprocess_operations": preprocess_operations,
            "hpc_operations": hpc_operations,
            "approval_requirements": approval_requirements,
            "expected_outputs": [
                output
                for operation in [*bio_operations, *bio_tool_operations, *hpc_operations]
                for output in operation["expected_outputs"]
            ],
            "resource_quota_estimate": {
                "hpc_operation_count": len(hpc_operations),
                "bio_operation_count": len(bio_operations),
                "bio_tool_operation_count": len(bio_tool_operations),
                "preprocess_operation_count": len(preprocess_operations),
                "max_runtime_minutes": sum(int(operation["resource_estimate"]["max_runtime_minutes"]) for operation in hpc_operations),
                "provider_requests": sum(int(operation["quota_estimate"]["provider_requests"]) for operation in bio_operations),
                "local_tool_invocations": sum(int(operation["quota_estimate"]["local_tool_invocations"]) for operation in bio_tool_operations),
            },
            "doc_hints": self._plan_doc_hints(operations),
            "operations": operations,
        }
        digest = hashlib.sha256(json.dumps(plan_without_digest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"plan_digest": digest, **plan_without_digest}

    def _literal_pipeline_artifact_get_ids(self, code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        artifact_ids: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "get":
                continue
            owner = func.value
            if not isinstance(owner, ast.Name) or owner.id != "artifacts":
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue
            artifact_id = node.args[0].value
            if artifact_id and artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
        return artifact_ids

    def _forbidden_pipeline_network_usage(self, code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        forbidden: list[str] = []
        blocked_roots = {"requests", "httpx", "urllib"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", maxsplit=1)[0]
                    if root in blocked_roots or alias.name == "Bio.Entrez":
                        forbidden.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".", maxsplit=1)[0]
                if root in blocked_roots or module == "Bio.Entrez":
                    forbidden.append(module)
                elif module == "Bio":
                    forbidden.extend(f"Bio.{alias.name}" for alias in node.names if alias.name == "Entrez")
        return sorted(set(forbidden))

    def _forbidden_pipeline_process_usage(self, code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        forbidden: list[str] = []
        forbidden_os_calls = {"system", "popen", "spawnv", "spawnvp", "spawnve", "execv", "execve", "execl", "execle", "execlp", "execlpe"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        forbidden.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    forbidden.append("subprocess")
                elif node.module == "os":
                    forbidden.extend(f"os.{alias.name}" for alias in node.names if alias.name in forbidden_os_calls)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id == "os" and node.func.attr in forbidden_os_calls:
                    forbidden.append(f"os.{node.func.attr}")
        return sorted(set(forbidden))

    def _planned_pipeline_operation_key(self, method: str, artifact_ids: list[str]) -> str:
        canonical = json.dumps({"method": method, "artifact_ids": artifact_ids}, sort_keys=True, separators=(",", ":"))
        return f"{method}:plan:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"

    def _planned_expected_outputs(self, method: str) -> list[dict[str, Any]]:
        if method == "hpc.fpocket":
            return [{"path": "fpocket.log", "kind": "log"}, {"path": "pockets/pockets.json", "kind": "result"}]
        if method == "hpc.vina":
            return [{"path": "vina.log", "kind": "log"}, {"path": "poses/vina_out.pdbqt", "kind": "structure"}]
        return []

    def _planned_bio_provider(self, method: str) -> str:
        return {
            "bio.ncbi_fetch_proteins": "ncbi",
            "bio.uniprot_fetch": "uniprot",
            "bio.hmmer_search": "ebi_hmmer",
        }.get(method, "unknown")

    def _planned_bio_expected_outputs(self, method: str) -> list[dict[str, Any]]:
        if method == "bio.ncbi_fetch_proteins":
            return [
                {"path": "bio/ncbi/proteins.fasta", "kind": "sequence"},
                {"path": "bio/ncbi/proteins.metadata.json", "kind": "result"},
            ]
        if method == "bio.uniprot_fetch":
            return [
                {"path": "bio/uniprot/sequences.fasta", "kind": "sequence"},
                {"path": "bio/uniprot/metadata.json", "kind": "result"},
            ]
        if method == "bio.hmmer_search":
            return [
                {"path": "bio/hmmer/raw_hits.json", "kind": "result"},
                {"path": "bio/hmmer/parsed_hits.csv", "kind": "result"},
            ]
        return []

    def _planned_bio_quota_estimate(self, method: str) -> dict[str, Any]:
        return {"provider_requests": 1, "operation": method, "pagination_pages": 1}

    def _planned_bio_tool_expected_outputs(self, method: str) -> list[dict[str, Any]]:
        return {
            "bio_tools.cdhit": [
                {"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence"},
                {"path": "bio_tools/cdhit/clusters.csv", "kind": "result"},
            ],
            "bio_tools.mafft": [{"path": "bio_tools/mafft/alignment.fasta", "kind": "sequence"}],
            "bio_tools.hmmbuild": [{"path": "bio_tools/hmmbuild/model.hmm", "kind": "result"}],
            "bio_tools.hmmalign": [{"path": "bio_tools/hmmalign/aligned.fasta", "kind": "sequence"}],
            "bio_tools.hmmer_search_cli": [
                {"path": "bio_tools/hmmer_search_cli/hits.csv", "kind": "result"},
                {"path": "bio_tools/hmmer_search_cli/tool.log", "kind": "log"},
            ],
        }.get(method, [])

    def _planned_bio_tool_resource_estimate(self, method: str) -> dict[str, Any]:
        if method in {"bio_tools.hmmer_search_cli", "bio_tools.mafft"}:
            return {"cpu": 4, "memory_gb": 8, "max_runtime_minutes": 60}
        return {"cpu": 2, "memory_gb": 4, "max_runtime_minutes": 30}

    def _planned_resource_estimate(self, method: str) -> dict[str, Any]:
        if method == "hpc.vina":
            return {"cpu": 4, "memory_gb": 8, "max_runtime_minutes": 120}
        return {"cpu": 2, "memory_gb": 4, "max_runtime_minutes": 60}

    def _planned_quota_estimate(self, method: str) -> dict[str, Any]:
        return {"hpc_jobs": 1, "operation": method}

    def _plan_doc_hints(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []
        seen: set[tuple[str | None, str | None]] = set()
        for operation in operations:
            key = (
                None if operation.get("doc_keyword") is None else str(operation.get("doc_keyword")),
                None if operation.get("doc_id") is None else str(operation.get("doc_id")),
            )
            if key in seen or key == (None, None):
                continue
            seen.add(key)
            hints.append({"doc_keyword": key[0], "doc_id": key[1]})
        return hints

    def _validate_pipeline_plan_inputs(
        self,
        *,
        session_id: str,
        execution_plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        for operation in list(execution_plan.get("hpc_operations") or []):
            if operation.get("method") != "hpc.fpocket":
                continue
            artifact_ids = [str(value) for value in list(operation.get("artifact_ids") or [])]
            if not artifact_ids:
                continue
            artifact = self.repositories.artifacts.get(artifact_ids[0])
            if artifact is not None and artifact.session_id != session_id:
                continue
            try:
                self._validate_fpocket_artifact(artifact_ids[0])
            except PipelineSdkFailure as exc:
                return {
                    "type": exc.error_type,
                    "stage": exc.stage,
                    "retryable": exc.retryable,
                    "message": exc.message,
                    "hint": exc.hint,
                    "sdk_method": exc.sdk_method,
                }
        return None

    def _pipeline_idempotency_key(
        self,
        *,
        task_id: str,
        code_digest: str,
        inputs: dict[str, Any],
        phase: str,
    ) -> str:
        inputs_digest = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
        return f"{task_id}:execution.pipeline:{phase}:{code_digest[:12]}:{inputs_digest}"

    def _find_invocation_by_idempotency_key(
        self, *, session_id: str, idempotency_key: str
    ) -> EngineInvocation | None:
        for invocation in self.repositories.invocations.list_by_session(session_id):
            if invocation.idempotency_key == idempotency_key:
                return invocation
        return None

    def _fail_pipeline_start(
        self,
        *,
        session_id: str,
        task_id: str,
        code_digest: str,
        inputs: dict[str, Any],
        invocation_id: str | None,
        lane_id: str | None,
        idempotency_key: str | None,
        error_code: str,
        message: str,
        hint: str,
        error_type: str | None = None,
        stage: str = "pipeline_start_validation",
        retryable: bool = False,
        sdk_method: str | None = None,
        source_metadata: dict[str, Any] | None = None,
    ) -> ExecutionStartResult:
        self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        output_id = _new_document_id("eng_out")
        resolved_idempotency_key = idempotency_key or self._pipeline_idempotency_key(
            task_id=task_id,
            code_digest=code_digest,
            inputs=inputs,
            phase="validation_error",
        )
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=input_id,
            output_ref=output_id,
            approval_id=None,
            idempotency_key=resolved_idempotency_key,
            started_at=now,
            finished_at=now,
        )
        payload = {
            "pipeline": {
                "code_digest": code_digest,
                **({} if source_metadata is None else dict(source_metadata)),
                "inputs": inputs,
                "sandbox_status": "not_started",
                "error": {
                    "type": error_type or error_code,
                    "stage": stage,
                    "retryable": retryable,
                    "error_code": error_code,
                    "message": message,
                    "hint": hint,
                    "sdk_method": sdk_method,
                },
            }
        }
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_input",
                payload={"task_id": task_id, "lane_id": effective_lane_id, "pipeline": payload["pipeline"]},
                created_at=now,
                updated_at=now,
            )
        )
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_result",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )
        return ExecutionStartResult(
            invocation=invocation,
            run=None,
            approval=None,
            parsed_result=ExecutionParsedResult(result_summary=message, structured_findings=payload["pipeline"]),
        )

    def _start_pipeline_dry_run(
        self,
        *,
        session_id: str,
        task_id: str,
        code_digest: str,
        pipeline_metadata: dict[str, Any],
        invocation_id: str | None,
        lane_id: str | None,
        idempotency_key: str | None,
    ) -> ExecutionStartResult:
        self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        output_id = _new_document_id("eng_out")
        resolved_idempotency_key = idempotency_key or self._pipeline_idempotency_key(
            task_id=task_id,
            code_digest=code_digest,
            inputs=dict(pipeline_metadata.get("inputs") or {}),
            phase="dry_run",
        )
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=input_id,
            output_ref=output_id,
            approval_id=None,
            idempotency_key=resolved_idempotency_key,
            started_at=now,
            finished_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_input",
                payload={
                    "task_id": task_id,
                    "lane_id": effective_lane_id,
                    "pipeline": pipeline_metadata,
                },
                created_at=now,
                updated_at=now,
            )
        )
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="execution_result",
                payload={
                    "dry_run": True,
                    "code_digest": code_digest,
                    "source_code_artifact_id": pipeline_metadata.get("source_code_artifact_id"),
                    "source_code_digest": pipeline_metadata.get("source_code_digest"),
                    "source_code_version": pipeline_metadata.get("source_code_version"),
                    "plan": {
                        "sandbox_status": "not_started",
                        **dict(pipeline_metadata["execution_plan"]),
                    },
                },
                created_at=now,
                updated_at=now,
            )
        )
        return ExecutionStartResult(
            invocation=invocation,
            run=None,
            approval=None,
            parsed_result=ExecutionParsedResult(
                result_summary="Pipeline dry-run completed.",
                structured_findings={
                    "code_digest": code_digest,
                    "source_code_artifact_id": pipeline_metadata.get("source_code_artifact_id"),
                    "source_code_digest": pipeline_metadata.get("source_code_digest"),
                    "source_code_version": pipeline_metadata.get("source_code_version"),
                    "plan": pipeline_metadata["execution_plan"],
                },
            ),
        )


def register_execution_tools(registry: ToolRegistry, engine: ExecutionEngine) -> None:
    def start_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        task_id = str(invocation.arguments["task_id"])
        existing_task_invocation = next(
            (
                candidate
                for candidate in context.repositories.invocations.list_by_task(
                    session_id, task_id
                )
                if candidate.engine_name == engine.descriptor.engine_name
                and candidate.status
                not in {EngineInvocationStatus.FAILED, EngineInvocationStatus.CANCELLED}
            ),
            None,
        )
        if existing_task_invocation is not None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=(
                    "An execution pipeline invocation already exists for this task: "
                    f"{existing_task_invocation.invocation_id} "
                    f"status={existing_task_invocation.status.value}. "
                    "Use execution.pipeline.status for that invocation instead of starting another pipeline."
                ),
                task_id=existing_task_invocation.task_id,
                lane_id=existing_task_invocation.lane_id,
                status="existing_execution_invocation",
                summary="Use execution.pipeline.status for the existing execution invocation.",
                error_code="existing_execution_invocation",
                hint=(
                    "Call execution.pipeline.status with invocation_id="
                    f"{existing_task_invocation.invocation_id!r}; then update the task with the result."
                ),
                details={
                    "invocation_id": existing_task_invocation.invocation_id,
                    "invocation_status": existing_task_invocation.status.value,
                },
            )
        result = engine.start_pipeline(
            session_id=session_id,
            task_id=task_id,
            code_artifact_id=None
            if invocation.arguments.get("code_artifact_id") is None
            else str(invocation.arguments["code_artifact_id"]),
            code=None if invocation.arguments.get("code") is None else str(invocation.arguments["code"]),
            inputs=None if invocation.arguments.get("inputs") is None else dict(invocation.arguments["inputs"]),
            dry_run=bool(invocation.arguments.get("dry_run", False)),
            invocation_id=None if invocation.arguments.get("invocation_id") is None else str(invocation.arguments["invocation_id"]),
            lane_id=invocation.lane_id if invocation.arguments.get("lane_id") is None else str(invocation.arguments["lane_id"]),
            idempotency_key=None if invocation.arguments.get("idempotency_key") is None else str(invocation.arguments["idempotency_key"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status not in {EngineInvocationStatus.FAILED, EngineInvocationStatus.CANCELLED},
            content=json.dumps(result.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def status_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        status = engine.get_pipeline_status(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(status, sort_keys=True),
        )

    registry.register("execution.pipeline.start", start_handler)
    registry.register("execution.pipeline.status", status_handler)


__all__ = [
    "BioArtifactDraft",
    "BioDatabaseAdapter",
    "BioSdkResult",
    "BioToolsAdapter",
    "DefaultExecutionRequestCompiler",
    "DefaultExecutionResultParser",
    "DefaultPreprocessAdapter",
    "DeterministicBioDatabaseAdapter",
    "DeterministicBioToolsAdapter",
    "ExecutionArtifactRef",
    "ExecutionEngine",
    "ExecutionHandoff",
    "ExecutionOutcome",
    "ExecutionParsedResult",
    "PreprocessAdapter",
    "PreprocessArtifactDraft",
    "PreprocessResult",
    "ExecutionRequestCompiler",
    "ExecutionRunner",
    "ExecutionStartResult",
    "ExecutionStatusSnapshot",
    "register_execution_tools",
]
