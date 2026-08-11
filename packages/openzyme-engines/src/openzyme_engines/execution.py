from __future__ import annotations

import ast
import base64
import csv
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from decimal import InvalidOperation
from http import client as http_client
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import tempfile
import time
from typing import Any
from typing import Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from uuid import uuid4

from openzyme_runtime import ArtifactBoundaryError
from openzyme_runtime import ArtifactBoundaryService
from openzyme_runtime import EngineDescriptor
from openzyme_runtime import EngineDocumentRecord
from openzyme_runtime import AgentStepContext
from openzyme_runtime import ToolGovernance
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolRegistryProtocol
from openzyme_runtime import ToolResult
from openzyme_runtime import ToolSideEffect
from openzyme_runtime import ToolSpec
from openzyme_runtime import ToolValidationError
from openzyme_runtime import validate_arguments_against_schema
from openzyme_runtime import project_artifact_for_agent
from openzyme_runtime import sanitize_private_artifact_fields
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import RunRecord
from openzyme_domain import RunStatus
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain.control_plane import utc_now_iso
from openzyme_tools import compile_hpc_tool_request
from openzyme_tools import CDHIT_MEMBERSHIP_COLUMNS
from openzyme_tools import CDHIT_MEMBERSHIP_SCHEMA_ID
from openzyme_tools import parse_execution_result

_PIPELINE_WORKSPACE_DIRECTORIES = (
    "src",
    "input",
    "work",
    "output",
    "logs",
    "manifest",
)
_SANDBOX_IDENTITY_FIELDS = frozenset(
    "configured_image_ref immutable_image_ref image_digest pipeline_sdk_digest "
    "sandbox_protocol_version runtime_identity_digest".split()
)


def validate_closed_sandbox_runtime_identity(
    raw: object, *, configured_image_ref: str | None = None,
    image_digest: str | None = None, sdk_digest: str | None = None,
    protocol_version: str | None = None,
) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("missing")
    if set(raw) != _SANDBOX_IDENTITY_FIELDS or any(not isinstance(value, str) for value in raw.values()):
        raise ValueError("invalid")
    identity = dict(raw)
    components = {key: identity[key] for key in _SANDBOX_IDENTITY_FIELDS - {"runtime_identity_digest"}}
    digest = "sha256:" + hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if identity["immutable_image_ref"] != identity["image_digest"] or identity["runtime_identity_digest"] != digest:
        raise ValueError("invalid")
    expected = (("configured_image_ref", configured_image_ref), ("image_digest", image_digest),
                ("pipeline_sdk_digest", sdk_digest), ("sandbox_protocol_version", protocol_version))
    if any(value is not None and identity[key] != value for key, value in expected):
        raise ValueError("mismatch")
    return identity


class _DuplicateJsonKey(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__("duplicate JSON key")


class ExecutionHostCallContext(Protocol):
    repositories: Any


class ExecutionHostCallContextFactory(Protocol):
    def __call__(
        self,
        *,
        session_id: str,
        invocation_id: str,
    ) -> AbstractContextManager[ExecutionHostCallContext]: ...


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _ensure_pipeline_workspace_layout(
    workspace_path: Path,
    *,
    create: bool,
) -> None:
    if workspace_path.is_symlink():
        raise OSError("sandbox workspace root is a symlink")
    if create:
        if workspace_path.exists():
            raise OSError("new sandbox workspace root already exists")
        workspace_path.mkdir(parents=True, exist_ok=False)
    elif not workspace_path.is_dir():
        raise OSError("sandbox workspace root is missing")
    for name in _PIPELINE_WORKSPACE_DIRECTORIES:
        directory = workspace_path / name
        if directory.is_symlink():
            raise OSError("sandbox workspace directory is a symlink")
        if directory.exists():
            if not directory.is_dir():
                raise OSError("sandbox workspace entry is not a directory")
        elif create:
            directory.mkdir(exist_ok=False)
        else:
            raise OSError("sandbox workspace directory is missing")
        if directory.is_symlink() or not directory.is_dir():
            raise OSError("sandbox workspace directory is missing or invalid")


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
    if lowered.endswith((".fa", ".faa", ".fasta")):
        return ArtifactKind.SEQUENCE
    if lowered.endswith((".pdb", ".cif", ".mol2", ".sdf", ".pdbqt")):
        return ArtifactKind.STRUCTURE
    if lowered.endswith((".md", ".pdf", ".html")):
        return ArtifactKind.REPORT
    return ArtifactKind.RESULT


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
        "phase": raw.get("phase"),
        "effect_certainty": raw.get("effect_certainty"),
        "retry_eligibility": raw.get("retry_eligibility"),
        "reconciliation_required": raw.get("reconciliation_required"),
        "runner_attempt_receipt_digest": raw.get("runner_attempt_receipt_digest"),
    }
    return {key: value for key, value in details.items() if value is not None}


_TOOLCHAIN_RUNTIME_IDENTITY_FIELDS = (
    "schema_id",
    "attestation_scope",
    "execution_mode",
    "tool_id",
    "adapter_id",
    "command_template_id",
    "runner_contract_digest",
    "image_digest",
)
_SAFE_TOOLCHAIN_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_RUNNER_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RUNNER_STAGING_FAILURE_PHASES = frozenset(
    {
        "remote_layout",
        "input_parent",
        "input_transfer",
        "input_verification",
        "runner_control_transfer",
    }
)
_RUNNER_STAGING_FAILURE_FIELDS = frozenset(
    {
        "schema_id",
        "phase",
        "run_id",
        "input_ordinal",
        "content_digest",
        "returncode",
        "timed_out",
        "elapsed_seconds",
    }
)
_INVALID_RUNNER_STAGING_DIAGNOSTIC_REASON = (
    "HPC runner returned an invalid staging diagnostic."
)


def _project_toolchain_runtime_identity(
    value: Any,
    *,
    execution_mode: str,
) -> dict[str, str] | None:
    if execution_mode != "ssh" or not isinstance(value, dict):
        return None
    identity = {
        field: str(value.get(field) or "")
        for field in _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS
    }
    if (
        identity["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
        or identity["attestation_scope"] != "same_ssh_login_shell_pre_exec"
        or identity["execution_mode"] != "ssh"
        or any(
            _SAFE_TOOLCHAIN_IDENTIFIER_PATTERN.fullmatch(identity[field]) is None
            for field in ("tool_id", "adapter_id", "command_template_id")
        )
        or any(
            _SHA256_DIGEST_PATTERN.fullmatch(identity[field]) is None
            for field in ("runner_contract_digest", "image_digest")
        )
    ):
        return None
    return identity


def _project_runner_staging_failure(
    exc: Exception,
) -> tuple[bool, dict[str, Any] | None]:
    missing = object()
    try:
        projector = getattr(exc, "to_safe_diagnostic", missing)
    except Exception:  # noqa: BLE001 - hostile exception objects fail closed.
        return True, None
    if projector is missing:
        return False, None
    if not callable(projector):
        return True, None
    try:
        raw = projector()
        if not isinstance(raw, dict) or set(raw) != _RUNNER_STAGING_FAILURE_FIELDS:
            return True, None
        phase = str(raw.get("phase") or "")
        run_id = str(raw.get("run_id") or "")
        input_ordinal = raw.get("input_ordinal")
        content_digest = raw.get("content_digest")
        returncode = raw.get("returncode")
        timed_out = raw.get("timed_out")
        elapsed_seconds = raw.get("elapsed_seconds")
        if (
            raw.get("schema_id") != "runner_failure@1"
            or phase not in _RUNNER_STAGING_FAILURE_PHASES
            or _SAFE_RUNNER_RUN_ID_PATTERN.fullmatch(run_id) is None
            or isinstance(returncode, bool)
            or not isinstance(returncode, int)
            or not isinstance(timed_out, bool)
            or isinstance(elapsed_seconds, bool)
            or not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(float(elapsed_seconds))
            or float(elapsed_seconds) < 0
        ):
            return True, None
        if phase == "remote_layout":
            if input_ordinal is not None or content_digest is not None:
                return True, None
        elif phase == "runner_control_transfer":
            if (
                input_ordinal is not None
                or not isinstance(content_digest, str)
                or _SHA256_DIGEST_PATTERN.fullmatch(content_digest) is None
            ):
                return True, None
        elif (
            isinstance(input_ordinal, bool)
            or not isinstance(input_ordinal, int)
            or input_ordinal < 1
            or not isinstance(content_digest, str)
            or _SHA256_DIGEST_PATTERN.fullmatch(content_digest) is None
        ):
            return True, None
        return True, {
            "schema_id": "runner_failure@1",
            "phase": phase,
            "run_id": run_id,
            "input_ordinal": input_ordinal,
            "content_digest": content_digest,
            "returncode": returncode,
            "timed_out": timed_out,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
    except Exception:  # noqa: BLE001 - the complete validation boundary is closed.
        return True, None


def _legacy_runner_failure_reason(exc: Exception) -> str:
    try:
        return _scrub_provider_text(str(exc))
    except Exception:  # noqa: BLE001 - exception rendering is untrusted.
        return "HPC runner submission failed without a usable diagnostic."


@dataclass(frozen=True, slots=True)
class ExecutionArtifactRef:
    storage_uri: str
    relative_path: str
    kind: ArtifactKind
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "storage_uri": self.storage_uri,
            "relative_path": self.relative_path,
            "kind": self.kind.value,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: RunStatus
    execution_mode: str
    remote_run_dir: str
    raw_result: dict[str, Any]
    artifacts: tuple[ExecutionArtifactRef, ...] = ()
    exit_code: int | None = None
    toolchain_runtime_identity: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusSnapshot:
    run_id: str
    status: RunStatus
    raw_result: dict[str, Any]
    exit_code: int | None = None


class ExecutionRunner(Protocol):
    def submit_execution(
        self, session_id: str, payload: dict[str, Any]
    ) -> ExecutionOutcome: ...

    def get_execution_status(
        self,
        *,
        run_id: str,
    ) -> ExecutionStatusSnapshot: ...

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
    ) -> ExecutionOutcome: ...

    def cancel_execution(
        self,
        *,
        run_id: str,
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
        super().__init__(
            f"pipeline operation requires approval: {approval.approval_id}"
        )
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


BIO_PROVIDER_ROUTE_POLICY_IDS = {
    "bio.ncbi_fetch_proteins": "bio.ncbi_fetch_proteins.provider:v1",
    "bio.uniprot_fetch": "bio.uniprot_fetch.provider:v1",
    "bio.hmmer_search": "bio.hmmer_search.provider:v1",
    "rcsb_pdb.download_structure": "rcsb_pdb.download_structure.provider:v1",
}
BIO_TOOL_ROUTE_POLICY_IDS = {
    "bio_tools.cdhit": "bio_tools.cdhit.hpc:v1",
    "bio_tools.mafft": "bio_tools.mafft.hpc:v1",
    "bio_tools.hmmbuild": "bio_tools.hmmbuild.hpc:v1",
    "bio_tools.hmmalign": "bio_tools.hmmalign.hpc:v1",
    "bio_tools.hmmer_search_cli": "bio_tools.hmmer_search_cli.disabled:v1",
}

_HPC_RUNNER_TIMEOUT_ERROR_CODES = frozenset(
    {
        "timeout",
        "command_timeout",
        "hpc_runner_timeout",
        "ssh_timeout",
        "ssh_connection_timeout",
    }
)
_HPC_RUNNER_UNAVAILABLE_ERROR_CODES = frozenset({"ssh_connection_failed"})

STRUCTURE_TOOL_ROUTE_POLICY_IDS = {
    "structure_tools.fpocket": "structure_tools.fpocket.hpc:v1",
}
BIO_PROVIDER_NAMES = {
    "bio.ncbi_fetch_proteins": "ncbi",
    "bio.uniprot_fetch": "uniprot",
    "bio.hmmer_search": "ebi_hmmer",
    "rcsb_pdb.download_structure": "rcsb_pdb",
}
_SEQUENCE_DIGEST_INDEX_CONTRACT_ID = "canonical_sequence_digest_index@1"
BIO_SAFE_HEADER_NAMES = {
    "content-type",
    "date",
    "retry-after",
    "x-request-id",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-total-results",
    "x-uniprot-release",
    "x-uniprot-release-date",
}
BIO_SENSITIVE_KEY_FRAGMENTS = {
    "api_key",
    "apikey",
    "authorization",
    "cache_path",
    "credential",
    "database_mount",
    "database_path",
    "host_path",
    "local_path",
    "mount_path",
    "private_endpoint",
    "runner_config",
    "secret",
    "slurm_config",
    "ssh_config",
    "storage_uri",
    "temp_path",
    "token",
}
BIO_ERROR_CODE_MAP = {
    "bio_provider_timeout": "provider_timeout",
    "bio_schema_drift": "provider_schema_drift",
    "bio_pagination_failure": "provider_timeout",
    "invalid_batch_size": "provider_invalid_request",
    "invalid_hmm_artifact": "provider_invalid_request",
}


def _json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _sha256_text(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _is_sha256_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _sequence_digest_index_metadata(
    sequence_digests: dict[str, str],
) -> dict[str, Any]:
    canonical_index = {
        str(accession): str(sequence_digests[accession])
        for accession in sorted(sequence_digests)
    }
    return {
        "sequence_digest_count": len(canonical_index),
        "sequence_digest_index_digest": _sha256_text(_json_text(canonical_index)),
        "sequence_digest_index_contract_id": _SEQUENCE_DIGEST_INDEX_CONTRACT_ID,
    }


def _exact_optional_uniprot_batch_size(
    value: Any,
    *,
    sdk_method: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PipelineSdkFailure(
            error_type="invalid_batch_size",
            message="bio.uniprot_fetch batch_size must be an exact integer.",
            hint="Retry with batch_size omitted or set to a positive integer.",
            stage="bio_input_validation",
            retryable=False,
            sdk_method=sdk_method,
            details={"batch_size": value},
        )
    return value


def _scrub_provider_text(value: str) -> str:
    redacted = value
    redacted = re.sub(
        r"(?i)(api[_-]?key|token|secret|credential|authorization)=([^&\s]+)",
        r"\1=[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(bearer|basic)\s+[a-z0-9._~+/=-]+", r"\1 [redacted]", redacted
    )
    redacted = re.sub(
        r"(?i)(/tmp|/var/tmp|/home|/Users)/[^\s\"']+", "[redacted-path]", redacted
    )
    redacted = re.sub(
        r"(?i)(storage_uri|cache_path|temp_path|host_path)\s*[:=]\s*[^\s,}\"]+",
        r"\1=[redacted]",
        redacted,
    )
    return redacted


def _is_sensitive_provider_key(key: str) -> bool:
    lowered = key.strip().lower().replace("-", "_")
    return any(fragment in lowered for fragment in BIO_SENSITIVE_KEY_FRAGMENTS)


def _sanitize_provider_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_provider_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_provider_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_provider_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_provider_value(item) for item in value]
    if isinstance(value, str):
        return _scrub_provider_text(value)
    return value


def _sanitize_provider_headers(headers: dict[str, Any] | Any) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        lowered = str(key).lower()
        if (
            lowered in BIO_SAFE_HEADER_NAMES
            or lowered.startswith("x-ratelimit-")
            or lowered.startswith("x-rate-limit-")
        ):
            safe[lowered] = _scrub_provider_text(str(value))
    return safe


def _sanitize_provider_content(content: str) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return _scrub_provider_text(content)
    if (
        isinstance(parsed, dict)
        and parsed.get("schema_id") == "provider_raw_http_response_set@1"
    ):
        responses = parsed.get("responses")
        if not isinstance(responses, list) or not responses:
            raise ValueError("provider raw response set requires response records")
        for record in responses:
            if not isinstance(record, dict):
                raise ValueError("provider raw response record must be an object")
            encoded = record.get("body_base64")
            digest = str(record.get("body_digest") or "")
            try:
                raw = base64.b64decode(str(encoded), validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "provider raw response body is not canonical base64"
                ) from exc
            if (
                record.get("body_encoding") != "base64"
                or record.get("size_bytes") != len(raw)
                or digest != _sha256_bytes(raw)
                or record.get("headers")
                != _sanitize_provider_headers(record.get("headers") or {})
            ):
                raise ValueError("provider raw response identity is inconsistent")
        return _json_text(parsed)
    return _json_text(_sanitize_provider_value(parsed))


@dataclass(frozen=True, slots=True)
class BioProviderHttpResponse:
    status_code: int
    headers: dict[str, str]
    body: str
    body_bytes: bytes
    url: str

    @property
    def body_digest(self) -> str:
        return _sha256_bytes(self.body_bytes)


_UNIPROT_IDENTITY_CONTRACT_ID = "uniprot_primary_sequence_identity@2"
_HMMER_NONTERMINAL_JOB_STATUSES = frozenset(
    {
        "PENDING",
        "RUNNING",
        "STARTED",
        "SUBMITTED",
        "QUEUED",
        "RETRY",
    }
)
_HMMER_PAGE_SIZE_CAP = 1_000
_HMMER_MAX_HITS_CAP = 100_000
EBI_HMMER_DURABLE_DISPATCH_RECEIPT_SCHEMA_ID = (
    "ebi_hmmer_durable_dispatch_receipt@1"
)
EBI_HMMER_DURABLE_POLL_RECEIPT_SCHEMA_ID = "ebi_hmmer_durable_poll_receipt@1"


def _extract_ebi_hmmer_job_id(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = body.strip()
    if isinstance(payload, dict):
        for key in ("id", "job_id", "jobId", "uuid"):
            value = payload.get(key)
            if value:
                return str(value)
    if isinstance(payload, str):
        match = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}", payload)
        if match:
            return match.group(0)
        if payload:
            return payload.strip().strip('"')
    raise PipelineSdkFailure(
        error_type="provider_schema_drift",
        message="EBI HMMER submit response did not include a job id.",
        hint="Inspect provider response compatibility before retrying.",
        stage="provider_submit_parse",
        retryable=False,
        sdk_method="bio.hmmer_search",
        details={
            "body_excerpt": _scrub_provider_text(body[:1000]),
            "response_digest": _sha256_text(body),
        },
    )


@dataclass(frozen=True, slots=True)
class BioProviderHttpConfig:
    ncbi_email: str | None = None
    ncbi_tool: str = "openzyme"
    ebi_hmmer_email: str | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0)
    batch_size_cap: int = 100
    uniprot_operation_accession_cap: int = 100_000
    uniprot_page_cap_per_query: int = 100
    hmmer_poll_interval_seconds: float = 5.0
    hmmer_poll_timeout_seconds: float = 3300.0
    hmmer_page_size: int = 1000
    hmmer_max_hits: int = 100000
    user_agent: str = "OpenZyme/3 provider adapter"

    @classmethod
    def from_env(cls) -> "BioProviderHttpConfig":
        return cls(
            ncbi_email=os.getenv("OPENZYME_NCBI_EMAIL")
            or os.getenv("NCBI_EMAIL")
            or None,
            ncbi_tool=os.getenv("OPENZYME_NCBI_TOOL")
            or os.getenv("NCBI_TOOL")
            or "openzyme",
            ebi_hmmer_email=(
                os.getenv("OPENZYME_EBI_HMMER_EMAIL")
                or os.getenv("EBI_HMMER_EMAIL")
                or None
            ),
        )


@dataclass(frozen=True, slots=True)
class BioArtifactDraft:
    relative_path: str
    kind: ArtifactKind
    title: str
    content: str
    format: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _PreparedBioArtifactDraft:
    draft: BioArtifactDraft
    storage_path: Path
    workspace_relative_path: PurePosixPath
    safe_content: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class BioSdkResult:
    provider: str
    operation: str
    summary: dict[str, Any]
    artifacts: tuple[BioArtifactDraft, ...]
    warnings: tuple[dict[str, Any], ...] = ()
    provider_observation: dict[str, Any] | None = None
    api_version: str | None = None


@dataclass(frozen=True, slots=True)
class HmmerProviderDispatch:
    job_id: str
    submit_response: BioProviderHttpResponse
    normalized_database: str
    page_size: int
    max_hits: int
    query_hmm_digest: str
    request_payload_digest: str
    poll_interval_seconds: float
    poll_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HmmerProviderPoll:
    job_id: str
    page_size: int
    status: str
    payload: dict[str, Any]
    response: BioProviderHttpResponse


@dataclass(frozen=True, slots=True)
class _PreparedHmmerSearch:
    hmm_artifact: SessionArtifactRecord
    normalized_database: str
    page_size: int
    max_hits: int
    hmm_text: str
    request_payload: dict[str, Any]
    query_hmm_digest: str
    request_payload_digest: str


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
        source_sequence_identities: dict[str, dict[str, str]] | None = None,
        sequence_mismatch_choices: dict[str, str] | None = None,
    ) -> BioSdkResult: ...

    def rcsb_download_structure(
        self,
        *,
        pdb_id: str,
        file_format: str,
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
        records = [
            self._protein_record(accession, provider="ncbi", reviewed=None)
            for accession in accessions
        ]
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
                    relative_path="provider_parsed/proteins.fasta",
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
                    relative_path="provider_parsed/proteins.metadata.json",
                    kind=ArtifactKind.RESULT,
                    title="ncbi_proteins.metadata.json",
                    content=json.dumps(metadata_payload, sort_keys=True, indent=2)
                    + "\n",
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
        source_sequence_identities: dict[str, dict[str, str]] | None = None,
        sequence_mismatch_choices: dict[str, str] | None = None,
    ) -> BioSdkResult:
        del source_sequence_identities, sequence_mismatch_choices
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
        records = [
            self._protein_record(accession, provider="uniprot", reviewed=True)
            for accession in accessions
        ]
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
            "pagination": {
                "page_count": max(
                    1,
                    (len(accessions) + effective_batch_size - 1)
                    // effective_batch_size,
                )
            },
        }
        return BioSdkResult(
            provider="uniprot",
            operation="bio.uniprot_fetch",
            summary=summary,
            warnings=warnings,
            artifacts=(
                self._draft(
                    provider="uniprot",
                    relative_path="provider_parsed/sequences.fasta",
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
                    relative_path="provider_parsed/metadata.json",
                    kind=ArtifactKind.RESULT,
                    title="uniprot_metadata.json",
                    content=json.dumps(metadata_payload, sort_keys=True, indent=2)
                    + "\n",
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

    def rcsb_download_structure(
        self,
        *,
        pdb_id: str,
        file_format: str,
        retrieved_at: str,
    ) -> BioSdkResult:
        normalized_id = self._normalize_pdb_id(
            pdb_id, sdk_method="rcsb_pdb.download_structure"
        )
        normalized_format = self._normalize_structure_format(
            file_format,
            sdk_method="rcsb_pdb.download_structure",
        )
        content = self._fixture_structure_content(normalized_id, normalized_format)
        digest = _sha256_text(content)
        locator = f"https://files.rcsb.org/download/{normalized_id}.{normalized_format}"
        summary = {
            "provider": "rcsb_pdb",
            "pdb_id": normalized_id,
            "format": normalized_format,
            "artifact_count": 1,
        }
        return BioSdkResult(
            provider="rcsb_pdb",
            operation="rcsb_pdb.download_structure",
            summary=summary,
            api_version="fixture",
            provider_observation={
                "provider": "rcsb_pdb",
                "api_version": "fixture",
                "requests": [
                    {
                        "method": "GET",
                        "url": "https://files.rcsb.org/download/{pdb_id}.{format}",
                        "status_code": 200,
                        "response_digest": digest,
                    }
                ],
            },
            artifacts=(
                self._draft(
                    provider="rcsb_pdb",
                    relative_path=f"provider_parsed/{normalized_id}.{normalized_format}",
                    kind=ArtifactKind.STRUCTURE,
                    title=f"{normalized_id}.{normalized_format}",
                    content=content,
                    format=normalized_format,
                    metadata={
                        "external_id": normalized_id,
                        "source_locator": locator,
                        "retrieved_at": retrieved_at,
                        "primary_output": True,
                        "provider_provenance": {
                            "provider": "rcsb_pdb",
                            "external_id": normalized_id,
                            "source_locator": locator,
                            "format": normalized_format,
                            "retrieved_at": retrieved_at,
                            "digest": digest,
                        },
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
                details={
                    "provider": "ebi_hmmer",
                    "database": normalized_database,
                    "cursor": "fixture-page-2",
                },
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
                    relative_path="provider_raw/raw_hits.json",
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
                    relative_path="provider_parsed/parsed_hits.csv",
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

    def _normalize_pdb_id(self, pdb_id: str, *, sdk_method: str) -> str:
        value = str(pdb_id).strip().upper()
        if not re.fullmatch(r"[0-9A-Z]{4}", value):
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="RCSB PDB id must be a four-character structure id.",
                hint="Use an RCSB structure id such as 6LEH.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"pdb_id": pdb_id},
            )
        return value

    def _normalize_structure_format(self, file_format: str, *, sdk_method: str) -> str:
        value = str(file_format or "pdb").strip().lower()
        if value == "mmcif":
            value = "cif"
        if value not in {"pdb", "cif"}:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="RCSB structure format must be pdb or cif.",
                hint="Retry with format='pdb' or format='cif'.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"format": file_format},
            )
        return value

    def _fixture_structure_content(self, pdb_id: str, file_format: str) -> str:
        if file_format == "cif":
            atoms = "\n".join(
                f"ATOM {idx} C C{idx % 4} ALA A {idx // 4 + 1} {idx}.0 {idx + 1}.0 {idx + 2}.0"
                for idx in range(1, 65)
            )
            return f"data_{pdb_id}\n#\n{atoms}\n#\n"
        lines = [f"HEADER    OPENZYME FIXTURE STRUCTURE              {pdb_id}"]
        atom_id = 1
        for residue in range(1, 17):
            for atom_name in ("N", "CA", "C", "O"):
                lines.append(
                    f"ATOM  {atom_id:5d} {atom_name:^4s} ALA A{residue:4d}    "
                    f"{residue + atom_id / 100:8.3f}{residue + 1.0:8.3f}{residue + 2.0:8.3f}"
                    "  1.00 20.00           C"
                )
                atom_id += 1
        lines.append("END")
        return "\n".join(lines) + "\n"

    def _protein_record(
        self, accession: str, *, provider: str, reviewed: bool | None
    ) -> dict[str, Any]:
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
        return "M" + "".join(
            alphabet[(seed + index) % len(alphabet)] for index in range(59)
        )

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
        response_digest = (
            f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        )
        return BioArtifactDraft(
            relative_path=relative_path,
            kind=kind,
            title=title,
            content=content,
            format=format,
            metadata={
                "producer": "host_supervised_bio_provider_fixture",
                "provider": provider,
                "format": format,
                "response_digest": response_digest,
                "tool_version": self.tool_version,
                "api_version": "fixture",
                **metadata,
            },
        )


class ProviderHttpBioDatabaseAdapter:
    api_version = "provider_http:v1"

    def __init__(
        self,
        config: BioProviderHttpConfig | None = None,
        *,
        urlopen: Any | None = None,
        sleep: Any | None = None,
    ) -> None:
        self.config = config or BioProviderHttpConfig.from_env()
        self._urlopen = urlopen or urllib_request.urlopen
        self._sleep = sleep or time.sleep

    @classmethod
    def from_env(cls) -> "ProviderHttpBioDatabaseAdapter":
        return cls(BioProviderHttpConfig.from_env())

    def ncbi_fetch_proteins(
        self,
        *,
        accessions: tuple[str, ...],
        fields: tuple[str, ...],
        retrieved_at: str,
    ) -> BioSdkResult:
        if not self.config.ncbi_email:
            raise PipelineSdkFailure(
                error_type="provider_identity_missing",
                message="NCBI provider identity is not configured.",
                hint="Set OPENZYME_NCBI_EMAIL before running bio.ncbi_fetch_proteins.",
                stage="provider_config_validation",
                retryable=False,
                sdk_method="bio.ncbi_fetch_proteins",
                details={"provider": "ncbi", "required_identity": "email"},
            )
        normalized = self._normalize_accessions(
            accessions,
            provider="ncbi",
            sdk_method="bio.ncbi_fetch_proteins",
            accession_cap=self.config.batch_size_cap,
        )
        query = {
            "db": "protein",
            "id": ",".join(normalized),
            "rettype": "fasta",
            "retmode": "text",
            "tool": self.config.ncbi_tool,
            "email": self.config.ncbi_email,
        }
        url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
            + urllib_parse.urlencode(query)
        )
        response = self._http_request(
            "GET", url, sdk_method="bio.ncbi_fetch_proteins", stage="provider_request"
        )
        fasta = response.body.strip() + ("\n" if response.body.strip() else "")
        if not fasta.startswith(">"):
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="NCBI returned a non-FASTA response for the requested protein accessions.",
                hint="Check accessions and retry with valid NCBI protein identifiers.",
                stage="provider_response_validation",
                retryable=False,
                sdk_method="bio.ncbi_fetch_proteins",
                details={
                    "provider": "ncbi",
                    "status_code": response.status_code,
                    "body_excerpt": _scrub_provider_text(response.body[:500]),
                    "response_digest": response.body_digest,
                },
            )
        records = self._parse_fasta_records(fasta)
        resolved_records = self._resolve_ncbi_records(
            requested_accessions=normalized,
            records=records,
            response=response,
        )
        canonical_fasta = "".join(
            str(record["fasta_record"]) for record in resolved_records
        )
        aggregate_fasta_digest = _sha256_text(canonical_fasta)
        metadata_payload = {
            "provider": "ncbi",
            "database": "protein",
            "fields": list(fields),
            "requested_accessions": list(normalized),
            "identity_contract_id": "ncbi_requested_resolved_protein_identity@1",
            "identity_complete": True,
            "records": [
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"sequence", "fasta_record"}
                }
                for record in resolved_records
            ],
            "retrieved_at": retrieved_at,
            "api_version": self.api_version,
            "response_digest": response.body_digest,
            "aggregate_fasta_digest": aggregate_fasta_digest,
            "headers": _sanitize_provider_headers(response.headers),
        }
        summary = {
            "provider": "ncbi",
            "database": "protein",
            "accession_count": len(normalized),
            "record_count": len(resolved_records),
            "warning_count": 0,
            "request_window": {"start": 0, "size": len(normalized)},
            "identity_complete": True,
            "identity_contract_id": "ncbi_requested_resolved_protein_identity@1",
            "aggregate_fasta_digest": aggregate_fasta_digest,
        }
        return BioSdkResult(
            provider="ncbi",
            operation="bio.ncbi_fetch_proteins",
            summary=summary,
            api_version=self.api_version,
            provider_observation={
                "provider": "ncbi",
                "api_version": self.api_version,
                "requests": [
                    {
                        "method": "GET",
                        "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                        "status_code": response.status_code,
                        "headers": _sanitize_provider_headers(response.headers),
                        "response_digest": response.body_digest,
                        "requested_accessions": list(normalized),
                        "resolved_accessions": [
                            str(record["resolved_accession"])
                            for record in resolved_records
                        ],
                        "aggregate_fasta_digest": aggregate_fasta_digest,
                    }
                ],
            },
            artifacts=(
                self._draft(
                    provider="ncbi",
                    relative_path="provider_raw/ncbi_efetch.response.json",
                    kind=ArtifactKind.RESULT,
                    title="ncbi_efetch.response.json",
                    content=self._raw_response_set(
                        provider="ncbi",
                        operation="bio.ncbi_fetch_proteins",
                        responses=[("efetch", response)],
                    ),
                    format="json",
                    metadata={
                        "database": "protein",
                        "retrieved_at": retrieved_at,
                        "provider_response_digest": response.body_digest,
                        "raw_response_schema_id": "provider_raw_http_response_set@1",
                    },
                ),
                self._draft(
                    provider="ncbi",
                    relative_path="provider_parsed/proteins.fasta",
                    kind=ArtifactKind.SEQUENCE,
                    title="proteins.fasta",
                    content=canonical_fasta,
                    format="fasta",
                    metadata={
                        "database": "protein",
                        "retrieved_at": retrieved_at,
                        "identity_contract_id": "ncbi_requested_resolved_protein_identity@1",
                        "aggregate_fasta_digest": aggregate_fasta_digest,
                        **_sequence_digest_index_metadata(
                            {
                                str(record["requested_accession"]): str(
                                    record["sequence_digest"]
                                )
                                for record in resolved_records
                            }
                        ),
                    },
                ),
                self._draft(
                    provider="ncbi",
                    relative_path="provider_parsed/proteins.metadata.json",
                    kind=ArtifactKind.RESULT,
                    title="proteins.metadata.json",
                    content=_json_text(metadata_payload),
                    format="json",
                    metadata={
                        "database": "protein",
                        "retrieved_at": retrieved_at,
                        "identity_contract_id": "ncbi_requested_resolved_protein_identity@1",
                        "aggregate_fasta_digest": aggregate_fasta_digest,
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
        source_sequence_identities: dict[str, dict[str, str]] | None = None,
        sequence_mismatch_choices: dict[str, str] | None = None,
    ) -> BioSdkResult:
        normalized = self._normalize_accessions(
            accessions,
            provider="uniprot",
            sdk_method="bio.uniprot_fetch",
            accession_cap=self.config.uniprot_operation_accession_cap,
        )
        effective_batch_size = self._bounded_batch_size(
            batch_size, sdk_method="bio.uniprot_fetch"
        )
        requested_fields = self._uniprot_fields(fields)
        query_batches = tuple(
            normalized[offset : offset + self.config.batch_size_cap]
            for offset in range(0, len(normalized), self.config.batch_size_cap)
        )
        pages: list[dict[str, Any]] = []
        page_responses: list[BioProviderHttpResponse] = []
        requests: list[dict[str, Any]] = []
        for query_batch_index, query_accessions in enumerate(query_batches, start=1):
            query = " OR ".join(
                f"accession:{urllib_parse.quote(accession)}"
                for accession in query_accessions
            )
            params = {
                "query": f"({query})",
                "format": "json",
                "size": str(effective_batch_size),
                "fields": ",".join(requested_fields),
            }
            next_url: str | None = (
                "https://rest.uniprot.org/uniprotkb/search?"
                + urllib_parse.urlencode(params)
            )
            page_in_query = 0
            query_accessions_digest = _sha256_text(_json_text(list(query_accessions)))
            query_accession_start = (query_batch_index - 1) * self.config.batch_size_cap
            while next_url is not None:
                try:
                    response = self._http_request(
                        "GET",
                        next_url,
                        sdk_method="bio.uniprot_fetch",
                        stage="provider_request",
                    )
                except PipelineSdkFailure as exc:
                    safe_http_details = {
                        key: value
                        for key, value in exc.details.items()
                        if key in {"status_code", "headers", "response_digest"}
                    }
                    if exc.details.get("reason") is not None:
                        safe_http_details["reason_digest"] = _sha256_text(
                            str(exc.details["reason"])
                        )
                    raise PipelineSdkFailure(
                        error_type=exc.error_type,
                        message=exc.message,
                        hint=exc.hint,
                        stage=exc.stage,
                        retryable=exc.retryable,
                        sdk_method=exc.sdk_method,
                        hpc_failure=exc.hpc_failure,
                        details={
                            **safe_http_details,
                            "query_batch_index": query_batch_index,
                            "query_batch_count": len(query_batches),
                            "query_accession_start": query_accession_start,
                            "query_accession_count": len(query_accessions),
                            "query_accessions_digest": query_accessions_digest,
                            "completed_page_count": len(pages),
                            "completed_pages_in_query": page_in_query,
                            "requested_page_in_query": page_in_query + 1,
                        },
                    ) from exc
                try:
                    payload = json.loads(
                        response.body,
                        object_pairs_hook=_unique_json_object,
                    )
                except _DuplicateJsonKey as exc:
                    raise self._uniprot_schema_failure(
                        "UniProt response contained a duplicate JSON key.",
                        details={
                            "duplicate_key_digest": _sha256_text(exc.key),
                            "duplicate_key_explanation": (
                                "A JSON object repeated one member name."
                            ),
                            "response_digest": response.body_digest,
                        },
                    ) from exc
                except json.JSONDecodeError as exc:
                    raise self._schema_failure(
                        "bio.uniprot_fetch",
                        "UniProt returned non-JSON content.",
                        response=response,
                    ) from exc
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("results"), list
                ):
                    raise self._schema_failure(
                        "bio.uniprot_fetch",
                        "UniProt response did not include a results list.",
                        response=response,
                    )
                page_in_query += 1
                pages.append(payload)
                page_responses.append(response)
                requests.append(
                    {
                        "method": "GET",
                        "page": len(pages),
                        "query_batch_index": query_batch_index,
                        "query_batch_count": len(query_batches),
                        "query_accession_start": query_accession_start,
                        "query_accession_count": len(query_accessions),
                        "query_accessions_digest": query_accessions_digest,
                        "page_in_query": page_in_query,
                        "status_code": response.status_code,
                        "headers": _sanitize_provider_headers(response.headers),
                        "response_digest": response.body_digest,
                    }
                )
                next_url = self._next_link(response.headers)
                if (
                    next_url is not None
                    and page_in_query >= self.config.uniprot_page_cap_per_query
                ):
                    raise PipelineSdkFailure(
                        error_type="provider_partial_result",
                        message="UniProt pagination exceeded the per-query page cap.",
                        hint="Reduce batch_size or inspect the provider query expansion.",
                        stage="provider_pagination",
                        retryable=False,
                        sdk_method="bio.uniprot_fetch",
                        details={
                            "provider": "uniprot",
                            "page_cap": self.config.uniprot_page_cap_per_query,
                            "query_batch_index": query_batch_index,
                            "query_accession_count": len(query_accessions),
                        },
                    )
        results = [item for page in pages for item in list(page.get("results") or [])]
        if not results:
            raise PipelineSdkFailure(
                error_type="provider_empty_result",
                message="UniProt returned no records for the requested candidate accessions.",
                hint="Do not continue the AOX identity chain without a terminal empty/failure receipt.",
                stage="provider_response_validation",
                retryable=False,
                sdk_method="bio.uniprot_fetch",
                details={
                    "provider": "uniprot",
                    "requested_accessions": list(normalized),
                    "response_digests": [
                        response.body_digest for response in page_responses
                    ],
                },
            )
        warnings: list[dict[str, Any]] = []
        normalized_records, inactive_records = self._normalize_uniprot_records(
            requested_accessions=normalized,
            pages=pages,
            requests=requests,
            retrieved_at=retrieved_at,
            source_sequence_identities=source_sequence_identities,
            sequence_mismatch_choices=sequence_mismatch_choices,
        )
        inactive_deleted_record_count = sum(
            record["inactive_reason"]["inactive_reason_type"] == "DELETED"
            for record in inactive_records
        )
        inactive_merged_record_count = sum(
            record["inactive_reason"]["inactive_reason_type"] == "MERGED"
            for record in inactive_records
        )
        fasta = "".join(str(record["fasta_record"]) for record in normalized_records)
        release = self._uniprot_release(requests)
        release_date = self._uniprot_release_date(requests)
        response_digests = [response.body_digest for response in page_responses]
        aggregate_response_digest = _sha256_text(_json_text(response_digests))
        metadata_payload = {
            "provider": "uniprot",
            "database": "uniprotkb",
            "fields": requested_fields,
            "batch_size": effective_batch_size,
            "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
            "requested_accessions": list(normalized),
            "records": [
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"fasta_record"}
                }
                for record in normalized_records
            ],
            "inactive_records": inactive_records,
            "active_record_count": len(normalized_records),
            "inactive_record_count": len(inactive_records),
            "inactive_deleted_record_count": inactive_deleted_record_count,
            "inactive_merged_record_count": inactive_merged_record_count,
            "warnings": warnings,
            "retrieved_at": retrieved_at,
            "uniprot_release": release,
            "uniprot_release_date": release_date,
            "response_digests": response_digests,
            "aggregate_response_digest": aggregate_response_digest,
            "source_sequence_identity_count": len(source_sequence_identities or {}),
            "sequence_mismatch_resolution_count": len(sequence_mismatch_choices or {}),
            "api_version": self.api_version,
        }
        summary = {
            "provider": "uniprot",
            "database": "uniprotkb",
            "accession_count": len(normalized),
            "record_count": len(normalized_records) + len(inactive_records),
            "active_record_count": len(normalized_records),
            "inactive_record_count": len(inactive_records),
            "inactive_deleted_record_count": inactive_deleted_record_count,
            "inactive_merged_record_count": inactive_merged_record_count,
            "warning_count": len(warnings),
            "request_window": {"start": 0, "size": effective_batch_size},
            "pagination": {
                "page_count": len(pages),
                "page_size": effective_batch_size,
                "page_cap_per_query": self.config.uniprot_page_cap_per_query,
                "query_batch_count": len(query_batches),
                "query_batch_size_cap": self.config.batch_size_cap,
            },
            "identity_complete": (
                len(normalized_records) + len(inactive_records) == len(normalized)
            ),
            "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
            "uniprot_release": release,
            "uniprot_release_date": release_date,
            "aggregate_response_digest": aggregate_response_digest,
            "source_sequence_identity_count": len(source_sequence_identities or {}),
            "sequence_mismatch_resolution_count": len(sequence_mismatch_choices or {}),
        }
        artifacts = [
            self._draft(
                provider="uniprot",
                relative_path="provider_raw/pages.json",
                kind=ArtifactKind.RESULT,
                title="uniprot_pages.json",
                content=self._raw_response_set(
                    provider="uniprot",
                    operation="bio.uniprot_fetch",
                    responses=[
                        (f"page:{page}", response)
                        for page, response in enumerate(page_responses, start=1)
                    ],
                ),
                format="json",
                metadata={
                    "database": "uniprotkb",
                    "retrieved_at": retrieved_at,
                    "uniprot_release": release,
                    "uniprot_release_date": release_date,
                    "provider_response_digests": [
                        str(request["response_digest"]) for request in requests
                    ],
                    "aggregate_response_digest": aggregate_response_digest,
                    "raw_response_schema_id": "provider_raw_http_response_set@1",
                },
            )
        ]
        fasta_metadata = {
            "database": "uniprotkb",
            "retrieved_at": retrieved_at,
            "uniprot_release": release,
            "uniprot_release_date": release_date,
            "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
            **_sequence_digest_index_metadata(
                {
                    str(record["primary_accession"]): str(record["sequence_digest"])
                    for record in normalized_records
                }
            ),
        }
        if not fasta:
            fasta_metadata.update(
                {
                    "validation_profile": "fasta_zero_records@1",
                    "empty_result_reason": "uniprot_no_active_sequence_records",
                    "derivation_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
                }
            )
        artifacts.append(
            self._draft(
                provider="uniprot",
                relative_path="provider_parsed/sequences.fasta",
                kind=ArtifactKind.SEQUENCE,
                title="sequences.fasta",
                content=fasta,
                format="fasta",
                metadata=fasta_metadata,
            )
        )
        artifacts.append(
            self._draft(
                provider="uniprot",
                relative_path="provider_parsed/metadata.json",
                kind=ArtifactKind.RESULT,
                title="metadata.json",
                content=_json_text(metadata_payload),
                format="json",
                metadata={
                    "database": "uniprotkb",
                    "retrieved_at": retrieved_at,
                    "uniprot_release": release,
                    "uniprot_release_date": release_date,
                    "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
                    "aggregate_response_digest": aggregate_response_digest,
                },
            )
        )
        return BioSdkResult(
            provider="uniprot",
            operation="bio.uniprot_fetch",
            summary=summary,
            warnings=tuple(warnings),
            api_version=self.api_version,
            provider_observation={
                "provider": "uniprot",
                "api_version": self.api_version,
                "requests": requests,
                "pagination": {
                    "page_count": len(pages),
                    "page_size": effective_batch_size,
                    "page_cap_per_query": self.config.uniprot_page_cap_per_query,
                    "query_batch_count": len(query_batches),
                    "query_batch_size_cap": self.config.batch_size_cap,
                },
                "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
                "requested_accessions": list(normalized),
                "primary_accessions": [
                    str(record["primary_accession"]) for record in normalized_records
                ],
                "inactive_accessions": [
                    str(record["requested_accession"]) for record in inactive_records
                ],
                "active_record_count": len(normalized_records),
                "inactive_record_count": len(inactive_records),
                "inactive_deleted_record_count": inactive_deleted_record_count,
                "inactive_merged_record_count": inactive_merged_record_count,
                "uniprot_release": release,
                "uniprot_release_date": release_date,
                "aggregate_response_digest": aggregate_response_digest,
                "source_sequence_identity_count": len(source_sequence_identities or {}),
                "sequence_mismatch_resolution_count": len(
                    sequence_mismatch_choices or {}
                ),
            },
            artifacts=tuple(artifacts),
        )

    def rcsb_download_structure(
        self,
        *,
        pdb_id: str,
        file_format: str,
        retrieved_at: str,
    ) -> BioSdkResult:
        normalized_id = self._normalize_pdb_id(
            pdb_id, sdk_method="rcsb_pdb.download_structure"
        )
        normalized_format = self._normalize_structure_format(
            file_format,
            sdk_method="rcsb_pdb.download_structure",
        )
        url = f"https://files.rcsb.org/download/{urllib_parse.quote(normalized_id)}.{normalized_format}"
        response = self._http_request(
            "GET",
            url,
            sdk_method="rcsb_pdb.download_structure",
            stage="provider_request",
        )
        content = response.body.strip() + ("\n" if response.body.strip() else "")
        self._validate_structure_download(
            content,
            pdb_id=normalized_id,
            file_format=normalized_format,
            response=response,
        )
        digest = _sha256_text(content)
        summary = {
            "provider": "rcsb_pdb",
            "pdb_id": normalized_id,
            "format": normalized_format,
            "artifact_count": 1,
        }
        return BioSdkResult(
            provider="rcsb_pdb",
            operation="rcsb_pdb.download_structure",
            summary=summary,
            api_version=self.api_version,
            provider_observation={
                "provider": "rcsb_pdb",
                "api_version": self.api_version,
                "requests": [
                    {
                        "method": "GET",
                        "url": "https://files.rcsb.org/download/{pdb_id}.{format}",
                        "status_code": response.status_code,
                        "headers": _sanitize_provider_headers(response.headers),
                        "response_digest": digest,
                    }
                ],
            },
            artifacts=(
                self._draft(
                    provider="rcsb_pdb",
                    relative_path=f"provider_parsed/{normalized_id}.{normalized_format}",
                    kind=ArtifactKind.STRUCTURE,
                    title=f"{normalized_id}.{normalized_format}",
                    content=content,
                    format=normalized_format,
                    metadata={
                        "external_id": normalized_id,
                        "source_locator": url,
                        "retrieved_at": retrieved_at,
                        "primary_output": True,
                        "provider_provenance": {
                            "provider": "rcsb_pdb",
                            "external_id": normalized_id,
                            "source_locator": url,
                            "format": normalized_format,
                            "retrieved_at": retrieved_at,
                            "digest": digest,
                        },
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
        _durable_dispatch: HmmerProviderDispatch | None = None,
        _durable_polls: tuple[HmmerProviderPoll, ...] = (),
    ) -> BioSdkResult:
        prepared = self._prepare_hmmer_search(
            hmm_artifact=hmm_artifact,
            database=database,
            params=params,
            frozen_dispatch=_durable_dispatch,
        )
        normalized_database = prepared.normalized_database
        max_hits = prepared.max_hits
        page_size = prepared.page_size
        base = "https://www.ebi.ac.uk/Tools/hmmer/api/v1"
        if _durable_dispatch is None:
            dispatch = self._submit_prepared_hmmer_search(prepared)
            status_payload, status_requests = self._poll_hmmer_job(
                dispatch.job_id,
                page_size=page_size,
            )
        else:
            dispatch = _durable_dispatch
            self._validate_durable_hmmer_identity(
                prepared=prepared,
                dispatch=dispatch,
                polls=_durable_polls,
            )
            if not _durable_polls:
                raise PipelineSdkFailure(
                    error_type="provider_observation_missing",
                    message="Durable EBI HMMER materialization has no terminal poll.",
                    hint="Preserve the accepted job and continue exact-handle polling.",
                    stage="provider_poll",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "job_id": dispatch.job_id,
                    },
                )
            status_payload = dict(_durable_polls[-1].payload)
            status_requests = [
                self._hmmer_poll_request_record(poll) for poll in _durable_polls
            ]
        submit = dispatch.submit_response
        job_id = dispatch.job_id
        if str(status_payload.get("status") or "").upper() not in {"SUCCESS", "DONE"}:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="EBI HMMER job did not complete successfully.",
                hint="Inspect provider_error.json and retry with a compatible HMM/database pair.",
                stage="provider_poll",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={
                    "provider": "ebi_hmmer",
                    "job_id": job_id,
                    "job_status": status_payload.get("status"),
                    "job_payload": _sanitize_provider_value(status_payload),
                },
            )
        reported_hit_count = self._hmmer_reported_hit_count(status_payload)
        result_payloads, result_requests = self._fetch_hmmer_result_pages(
            base,
            job_id,
            page_size=page_size,
            max_hits=max_hits,
            expected_reported_hit_count=reported_hit_count,
        )
        page_digests = {
            int(request["page"]): str(request["response_digest"])
            for request in result_requests
            if request.get("page") is not None
        }
        raw_hits_with_provenance: list[tuple[int, str, dict[str, Any]]] = []
        for page_number, payload in enumerate(result_payloads, start=1):
            page_hits = self._hmmer_result_hits(
                payload,
                page=page_number,
                database=normalized_database,
            )
            page_digest = page_digests.get(page_number)
            if page_digest is None:
                raise PipelineSdkFailure(
                    error_type="provider_schema_drift",
                    message="EBI HMMER result page had no raw response digest.",
                    hint="Inspect the provider request log before retrying.",
                    stage="provider_results",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "provider_job_id": job_id,
                        "page": page_number,
                    },
                )
            raw_hits_with_provenance.extend(
                (page_number, page_digest, hit) for hit in page_hits
            )
        page_count = (
            self._hmmer_page_count(result_payloads[-1].get("page_count"))
            if result_payloads
            else None
        )
        retrieved_raw_hit_count = len(raw_hits_with_provenance)
        bounded_partial_result = (
            reported_hit_count > max_hits and retrieved_raw_hit_count >= max_hits
        )
        if (
            (
                reported_hit_count == 0
                and (retrieved_raw_hit_count != 0 or page_count != 0)
            )
            or (reported_hit_count > 0 and page_count in {None, 0})
            or (
                retrieved_raw_hit_count != reported_hit_count
                and not bounded_partial_result
            )
        ):
            raise PipelineSdkFailure(
                error_type="provider_partial_result",
                message="EBI HMMER result pages did not materialize the terminal reported hit set.",
                hint=(
                    "Do not continue with a gapped HMMER result; inspect the sealed poll "
                    "and explicit result-page transcript."
                ),
                stage="provider_results",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={
                    "provider": "ebi_hmmer",
                    "provider_job_id": job_id,
                    "reported_hit_count": reported_hit_count,
                    "retrieved_raw_hit_count": retrieved_raw_hit_count,
                    "declared_page_count": page_count,
                    "retrieved_page_count": len(result_payloads),
                    "page_size": page_size,
                    "max_hits": max_hits,
                },
            )
        truncated = (
            reported_hit_count > max_hits
            or len(raw_hits_with_provenance) > max_hits
            or (page_count is not None and len(result_payloads) < page_count)
        )
        hits = self._normalize_hmmer_hits(
            raw_hits_with_provenance[:max_hits],
            database=normalized_database,
        )
        warnings: list[dict[str, Any]] = []
        if not hits:
            warnings.append(
                {
                    "warning_code": "empty_results",
                    "stage": "provider_response",
                    "hint": "EBI HMMER completed successfully but returned no hits.",
                    "affected_range": {"start": 0, "end": 0},
                }
            )
        if truncated:
            warnings.append(
                {
                    "warning_code": "provider_result_truncated",
                    "stage": "provider_pagination",
                    "hint": "Only the top S13-capped HMMER hits were artifactized.",
                    "limit": max_hits,
                }
            )
        status_response_records = [
            (f"poll:{index}", request["_raw_response"])
            for index, request in enumerate(status_requests, start=1)
        ]
        result_response_records = [
            (f"result:{request.get('page') or index}", request["_raw_response"])
            for index, request in enumerate(result_requests, start=1)
        ]
        public_status_requests = [
            {key: value for key, value in request.items() if key != "_raw_response"}
            for request in status_requests
        ]
        public_result_requests = [
            {key: value for key, value in request.items() if key != "_raw_response"}
            for request in result_requests
        ]
        parsed_csv = self._hmmer_hits_csv(hits)
        parsed_hits_digest = _sha256_text(parsed_csv)
        request_payload_digest = prepared.request_payload_digest
        hmm_digest = prepared.query_hmm_digest
        summary = {
            "provider": "ebi_hmmer",
            "database": normalized_database,
            "query_hmm_artifact_id": hmm_artifact.artifact_id,
            "hit_count": len(hits),
            "warning_count": len(warnings),
            "provider_job_id": job_id,
            "parsed_hit_schema_id": "ebi_hmmer_refprot_hit@1"
            if normalized_database == "refprot"
            else "ebi_hmmer_hit@1",
            "parsed_hits_digest": parsed_hits_digest,
            "reported_hit_count": reported_hit_count,
            "retrieved_raw_hit_count": retrieved_raw_hit_count,
            "pagination": {
                "page_count": len(result_payloads),
                "declared_page_count": page_count,
                "truncated": truncated,
                "page_size": page_size,
                "max_hits": max_hits,
            },
        }
        return BioSdkResult(
            provider="ebi_hmmer",
            operation="bio.hmmer_search",
            summary=summary,
            warnings=tuple(warnings),
            api_version=self.api_version,
            provider_observation={
                "provider": "ebi_hmmer",
                "api_version": self.api_version,
                "provider_job_id": job_id,
                "operation": "bio.hmmer_search",
                "request_identity": {
                    "database": normalized_database,
                    "query_hmm_artifact_id": hmm_artifact.artifact_id,
                    "query_hmm_digest": hmm_digest,
                    "request_payload_digest": request_payload_digest,
                },
                "requests": [
                    {
                        "method": "POST",
                        "status_code": submit.status_code,
                        "headers": _sanitize_provider_headers(submit.headers),
                        "response_digest": submit.body_digest,
                    },
                    *public_status_requests,
                    *public_result_requests,
                ],
                "pagination": {
                    "page_count": len(result_payloads),
                    "declared_page_count": page_count,
                    "truncated": truncated,
                    "page_size": page_size,
                    "max_hits": max_hits,
                    "reported_hit_count": reported_hit_count,
                    "retrieved_raw_hit_count": retrieved_raw_hit_count,
                },
                "raw_page_digests": {
                    str(page): digest for page, digest in sorted(page_digests.items())
                },
                "parsed_hits_digest": parsed_hits_digest,
            },
            artifacts=(
                self._draft(
                    provider="ebi_hmmer",
                    relative_path="provider_raw/raw_hits.json",
                    kind=ArtifactKind.RESULT,
                    title="raw_hits.json",
                    content=self._raw_response_set(
                        provider="ebi_hmmer",
                        operation="bio.hmmer_search",
                        responses=[
                            ("submit", submit),
                            *status_response_records,
                            *result_response_records,
                        ],
                    ),
                    format="json",
                    metadata={
                        "database": normalized_database,
                        "query_hmm_artifact_id": hmm_artifact.artifact_id,
                        "retrieved_at": retrieved_at,
                        "query_hmm_digest": hmm_digest,
                        "request_payload_digest": request_payload_digest,
                        "raw_page_digests": {
                            str(page): digest
                            for page, digest in sorted(page_digests.items())
                        },
                        "raw_response_schema_id": "provider_raw_http_response_set@1",
                    },
                ),
                self._draft(
                    provider="ebi_hmmer",
                    relative_path="provider_parsed/parsed_hits.csv",
                    kind=ArtifactKind.RESULT,
                    title="parsed_hits.csv",
                    content=parsed_csv,
                    format="csv",
                    metadata={
                        "database": normalized_database,
                        "query_hmm_artifact_id": hmm_artifact.artifact_id,
                        "retrieved_at": retrieved_at,
                        "parsed_hit_schema_id": "ebi_hmmer_refprot_hit@1"
                        if normalized_database == "refprot"
                        else "ebi_hmmer_hit@1",
                        "required_columns": [
                            "target",
                            "accession",
                            "evalue",
                            "score",
                            "page",
                            "hit_index",
                            "evalue_numeric",
                            "score_numeric",
                            "raw_page_digest",
                            "raw_hit_digest",
                            "parsed_row_digest",
                        ],
                        "parsed_hits_digest": parsed_hits_digest,
                    },
                ),
            ),
        )

    def dispatch_hmmer_search(
        self,
        *,
        hmm_artifact: SessionArtifactRecord,
        database: str,
        params: dict[str, Any],
    ) -> HmmerProviderDispatch:
        """Submit one EBI HMMER job without entering a polling loop."""

        prepared = self._prepare_hmmer_search(
            hmm_artifact=hmm_artifact,
            database=database,
            params=params,
        )
        return self._submit_prepared_hmmer_search(prepared)

    def poll_hmmer_search(
        self,
        *,
        job_id: str,
        page_size: int,
    ) -> HmmerProviderPoll:
        """Observe one exact EBI HMMER job once."""

        if not job_id or job_id != job_id.strip():
            raise PipelineSdkFailure(
                error_type="provider_job_identity_invalid",
                message="Durable EBI HMMER polling requires one exact job id.",
                hint="Preserve the dispatch receipt and reject replacement submission.",
                stage="provider_poll",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer"},
            )
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size <= 0
            or page_size > _HMMER_PAGE_SIZE_CAP
        ):
            raise PipelineSdkFailure(
                error_type="provider_request_identity_invalid",
                message="Durable EBI HMMER polling page size is invalid.",
                hint="Use the page size frozen by the dispatch receipt.",
                stage="provider_poll",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", "page_size": str(page_size)},
            )
        base = "https://www.ebi.ac.uk/Tools/hmmer/api/v1"
        response = self._http_request(
            "GET",
            f"{base}/result/{urllib_parse.quote(job_id)}?"
            + urllib_parse.urlencode(
                {"format": "json", "page": 1, "page_size": page_size}
            ),
            sdk_method="bio.hmmer_search",
            stage="provider_poll",
        )
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise self._schema_failure(
                "bio.hmmer_search",
                "EBI HMMER job status was not JSON.",
                response=response,
            ) from exc
        if not isinstance(payload, dict):
            raise self._schema_failure(
                "bio.hmmer_search",
                "EBI HMMER job status was not an object.",
                response=response,
            )
        return HmmerProviderPoll(
            job_id=job_id,
            page_size=page_size,
            status=str(payload.get("status") or "").upper(),
            payload=dict(payload),
            response=response,
        )

    def materialize_hmmer_search(
        self,
        *,
        hmm_artifact: SessionArtifactRecord,
        database: str,
        params: dict[str, Any],
        retrieved_at: str,
        dispatch: HmmerProviderDispatch,
        polls: tuple[HmmerProviderPoll, ...],
    ) -> BioSdkResult:
        """Materialize terminal results from one frozen dispatch and poll chain."""

        return self.hmmer_search(
            hmm_artifact=hmm_artifact,
            database=database,
            params=params,
            retrieved_at=retrieved_at,
            _durable_dispatch=dispatch,
            _durable_polls=polls,
        )

    def _prepare_hmmer_search(
        self,
        *,
        hmm_artifact: SessionArtifactRecord,
        database: str,
        params: dict[str, Any],
        frozen_dispatch: HmmerProviderDispatch | None = None,
    ) -> _PreparedHmmerSearch:
        normalized_database = database.strip().lower()
        if normalized_database not in {
            "refprot",
            "swissprot",
            "uniprot",
            "pdb",
            "rp15",
            "rp35",
            "rp55",
            "rp75",
        }:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message=f"EBI HMMER database {database!r} is not allowed by the S13 provider policy.",
                hint="Use database='refprot' for the AOX/HMM main route.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", "database": database},
            )
        hmm_text = Path(hmm_artifact.storage_uri).read_text(
            encoding="utf-8", errors="replace"
        )
        max_hits = self._hmmer_positive_int_param(
            params,
            key="max_hits",
            default=(
                frozen_dispatch.max_hits
                if frozen_dispatch is not None
                else min(self.config.hmmer_max_hits, _HMMER_MAX_HITS_CAP)
            ),
            cap=(
                frozen_dispatch.max_hits
                if frozen_dispatch is not None
                else min(self.config.hmmer_max_hits, _HMMER_MAX_HITS_CAP)
            ),
        )
        page_size = self._hmmer_positive_int_param(
            params,
            key="page_size",
            default=(
                frozen_dispatch.page_size
                if frozen_dispatch is not None
                else min(self.config.hmmer_page_size, _HMMER_PAGE_SIZE_CAP)
            ),
            cap=(
                frozen_dispatch.page_size
                if frozen_dispatch is not None
                else min(self.config.hmmer_page_size, _HMMER_PAGE_SIZE_CAP)
            ),
        )
        request_payload: dict[str, Any] = {
            "input": hmm_text,
            "input_type": "hmm",
            "database": normalized_database,
        }
        if "evalue" in params and "E" not in params and params["evalue"] is not None:
            request_payload["E"] = self._hmmer_request_number(
                params["evalue"], field="E"
            )
        for key in ("E", "domE", "incE", "incdomE"):
            if key in params and params[key] is not None:
                request_payload[key] = self._hmmer_request_number(
                    params[key], field=key
                )
        if self.config.ebi_hmmer_email:
            request_payload["email_address"] = self.config.ebi_hmmer_email
        return _PreparedHmmerSearch(
            hmm_artifact=hmm_artifact,
            normalized_database=normalized_database,
            page_size=page_size,
            max_hits=max_hits,
            hmm_text=hmm_text,
            request_payload=request_payload,
            query_hmm_digest=_sha256_text(hmm_text),
            request_payload_digest=_sha256_text(_json_text(request_payload)),
        )

    def _submit_prepared_hmmer_search(
        self,
        prepared: _PreparedHmmerSearch,
    ) -> HmmerProviderDispatch:
        base = "https://www.ebi.ac.uk/Tools/hmmer/api/v1"
        submit = self._http_request(
            "POST",
            f"{base}/search/hmmsearch",
            data=json.dumps(prepared.request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            sdk_method="bio.hmmer_search",
            stage="provider_submit",
        )
        return HmmerProviderDispatch(
            job_id=self._extract_hmmer_job_id(submit.body),
            submit_response=submit,
            normalized_database=prepared.normalized_database,
            page_size=prepared.page_size,
            max_hits=prepared.max_hits,
            query_hmm_digest=prepared.query_hmm_digest,
            request_payload_digest=prepared.request_payload_digest,
            poll_interval_seconds=float(self.config.hmmer_poll_interval_seconds),
            poll_timeout_seconds=float(self.config.hmmer_poll_timeout_seconds),
        )

    def _validate_durable_hmmer_identity(
        self,
        *,
        prepared: _PreparedHmmerSearch,
        dispatch: HmmerProviderDispatch,
        polls: tuple[HmmerProviderPoll, ...],
    ) -> None:
        if (
            dispatch.normalized_database != prepared.normalized_database
            or dispatch.page_size != prepared.page_size
            or dispatch.max_hits != prepared.max_hits
            or dispatch.page_size > _HMMER_PAGE_SIZE_CAP
            or dispatch.max_hits > _HMMER_MAX_HITS_CAP
            or dispatch.query_hmm_digest != prepared.query_hmm_digest
            or dispatch.request_payload_digest != prepared.request_payload_digest
            or dispatch.poll_interval_seconds <= 0
            or dispatch.poll_interval_seconds > 300
            or dispatch.poll_timeout_seconds <= 0
            or dispatch.poll_timeout_seconds > 86_400
            or self._extract_hmmer_job_id(dispatch.submit_response.body)
            != dispatch.job_id
            or any(
                poll.job_id != dispatch.job_id
                or poll.page_size != dispatch.page_size
                or poll.status
                != str(poll.payload.get("status") or "").upper()
                for poll in polls
            )
        ):
            raise PipelineSdkFailure(
                error_type="provider_request_identity_invalid",
                message="Durable EBI HMMER receipt identity drifted.",
                hint="Preserve the accepted job and reject result publication.",
                stage="provider_result_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={
                    "provider": "ebi_hmmer",
                    "job_id": dispatch.job_id,
                },
            )

    @staticmethod
    def _hmmer_poll_request_record(poll: HmmerProviderPoll) -> dict[str, Any]:
        return {
            "method": "GET",
            "status_code": poll.response.status_code,
            "headers": _sanitize_provider_headers(poll.response.headers),
            "response_digest": poll.response.body_digest,
            "job_status": poll.status,
            "page": 1,
            "page_size": poll.page_size,
            "_raw_response": poll.response,
        }

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        sdk_method: str,
        stage: str,
    ) -> BioProviderHttpResponse:
        request_headers = {"User-Agent": self.config.user_agent, **dict(headers or {})}
        attempts = max(0, int(self.config.max_retries)) + 1
        for attempt in range(attempts):
            try:
                request = urllib_request.Request(
                    url, data=data, headers=request_headers, method=method
                )
                with self._urlopen(
                    request, timeout=self.config.timeout_seconds
                ) as response:
                    body_bytes = response.read()
                    body = body_bytes.decode("utf-8", errors="replace")
                    return BioProviderHttpResponse(
                        status_code=int(getattr(response, "status", 200)),
                        headers={
                            str(key): str(value)
                            for key, value in response.headers.items()
                        },
                        body=body,
                        body_bytes=body_bytes,
                        url=url,
                    )
            except urllib_error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if attempt < attempts - 1 and exc.code in {429, 500, 502, 503, 504}:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise self._http_failure(
                    sdk_method,
                    stage,
                    status_code=exc.code,
                    headers={
                        str(key): str(value) for key, value in exc.headers.items()
                    },
                    body=body,
                ) from exc
            except TimeoutError as exc:
                if attempt < attempts - 1:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise self._provider_failure(
                    sdk_method,
                    "provider_timeout",
                    "Provider request timed out.",
                    "Retry after provider recovery or reduce the request size.",
                    stage,
                    retryable=True,
                ) from exc
            except urllib_error.URLError as exc:
                if attempt < attempts - 1:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise self._provider_failure(
                    sdk_method,
                    "provider_unavailable",
                    "Provider endpoint was unavailable.",
                    "Retry after provider recovery.",
                    stage,
                    retryable=True,
                    details={"reason": _scrub_provider_text(str(exc.reason))},
                ) from exc
            except (http_client.RemoteDisconnected, ConnectionError, OSError) as exc:
                if attempt < attempts - 1:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise self._provider_failure(
                    sdk_method,
                    "provider_unavailable",
                    "Provider endpoint was unavailable.",
                    "Retry after provider recovery.",
                    stage,
                    retryable=True,
                    details={"reason": _scrub_provider_text(str(exc))},
                ) from exc
        raise AssertionError("unreachable provider request retry loop")

    def _hmmer_positive_int_param(
        self,
        params: dict[str, Any],
        *,
        key: str,
        default: int,
        cap: int,
    ) -> int:
        value = params.get(key)
        if value is None or value == "":
            return max(1, int(default))
        try:
            if isinstance(value, bool):
                raise ValueError("boolean is not an integer parameter")
            parsed = int(value)
            exact_value = Decimal(str(value))
            if not exact_value.is_finite() or exact_value != parsed:
                raise ValueError("value would be truncated to an integer")
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message=f"bio.hmmer_search params.{key} must be a positive integer.",
                hint=f"Retry with params.{key} omitted or set to a positive integer.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", key: str(value)},
            ) from exc
        if parsed <= 0:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message=f"bio.hmmer_search params.{key} must be a positive integer.",
                hint=f"Retry with params.{key} omitted or set to a positive integer.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", key: str(value)},
            )
        return min(parsed, max(1, int(cap)))

    def _hmmer_request_number(self, value: Any, *, field: str) -> float:
        if isinstance(value, bool):
            numeric = None
        else:
            try:
                numeric = Decimal(str(value))
            except InvalidOperation:
                numeric = None
        if numeric is None or not numeric.is_finite() or numeric < 0:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message=f"bio.hmmer_search params.{field} must be a finite non-negative number.",
                hint=f"Retry with params.{field} omitted or set to a numeric threshold.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer", field: str(value)},
            )
        return float(numeric)

    def _http_failure(
        self,
        sdk_method: str,
        stage: str,
        *,
        status_code: int,
        headers: dict[str, str],
        body: str,
    ) -> PipelineSdkFailure:
        if status_code == 429:
            code = "provider_rate_limited"
            retryable = True
        elif 400 <= status_code < 500:
            code = "provider_invalid_request"
            retryable = False
        else:
            code = "provider_unavailable"
            retryable = True
        return self._provider_failure(
            sdk_method,
            code,
            f"Provider HTTP request failed with status {status_code}.",
            "Inspect provider_error.json and retry only if the provider condition is transient.",
            stage,
            retryable=retryable,
            details={
                "status_code": status_code,
                "headers": _sanitize_provider_headers(headers),
                "body_excerpt": _scrub_provider_text(body[:1000]),
                "response_digest": _sha256_text(body),
            },
        )

    def _provider_failure(
        self,
        sdk_method: str,
        error_type: str,
        message: str,
        hint: str,
        stage: str,
        *,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type=error_type,
            message=message,
            hint=hint,
            stage=stage,
            retryable=retryable,
            sdk_method=sdk_method,
            details=details,
        )

    def _schema_failure(
        self, sdk_method: str, message: str, *, response: BioProviderHttpResponse
    ) -> PipelineSdkFailure:
        return self._provider_failure(
            sdk_method,
            "provider_schema_drift",
            message,
            "Inspect provider_observation.json before treating this as an empty result.",
            "provider_response_parse",
            retryable=False,
            details={
                "status_code": response.status_code,
                "headers": _sanitize_provider_headers(response.headers),
                "body_excerpt": _scrub_provider_text(response.body[:1000]),
                "response_digest": response.body_digest,
            },
        )

    def _retry_delay(self, attempt: int) -> float:
        if attempt < len(self.config.retry_backoff_seconds):
            return self.config.retry_backoff_seconds[attempt]
        return (
            self.config.retry_backoff_seconds[-1]
            if self.config.retry_backoff_seconds
            else 0.0
        )

    def _normalize_accessions(
        self,
        accessions: tuple[str, ...],
        *,
        provider: str,
        sdk_method: str,
        accession_cap: int,
    ) -> tuple[str, ...]:
        normalized: list[str] = []
        for index, accession in enumerate(accessions):
            value = str(accession).strip()
            if not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                raise PipelineSdkFailure(
                    error_type="provider_invalid_request",
                    message=f"Invalid {provider} accession at index {index}.",
                    hint="Use provider accession identifiers without whitespace or punctuation.",
                    stage="provider_request_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"accession": accession, "index": index},
                )
            normalized.append(value)
        if not normalized:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message=f"{provider} fetch requires at least one accession.",
                hint="Pass one or more accession strings.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        if len(normalized) > accession_cap:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message=f"{provider} fetch exceeds the configured operation accession cap.",
                hint="Reduce the candidate set before submitting another controlled operation.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={
                    "accession_count": len(normalized),
                    "limit": accession_cap,
                },
            )
        accession_counts: dict[str, int] = {}
        for accession in normalized:
            accession_counts[accession] = accession_counts.get(accession, 0) + 1
        duplicate_accessions = sorted(
            accession for accession, count in accession_counts.items() if count > 1
        )
        if duplicate_accessions:
            raise PipelineSdkFailure(
                error_type="provider_duplicate_identity",
                message=f"{provider} fetch received duplicate accession identities.",
                hint="Submit every provider accession exactly once.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={
                    "provider": provider,
                    "duplicate_accessions": duplicate_accessions,
                },
            )
        return tuple(normalized)

    def _normalize_pdb_id(self, pdb_id: str, *, sdk_method: str) -> str:
        value = str(pdb_id).strip().upper()
        if not re.fullmatch(r"[0-9A-Z]{4}", value):
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="RCSB PDB id must be a four-character structure id.",
                hint="Use an RCSB structure id such as 6LEH.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"pdb_id": pdb_id},
            )
        return value

    def _normalize_structure_format(self, file_format: str, *, sdk_method: str) -> str:
        value = str(file_format or "pdb").strip().lower()
        if value == "mmcif":
            value = "cif"
        if value not in {"pdb", "cif"}:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="RCSB structure format must be pdb or cif.",
                hint="Retry with format='pdb' or format='cif'.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"format": file_format},
            )
        return value

    def _validate_structure_download(
        self,
        content: str,
        *,
        pdb_id: str,
        file_format: str,
        response: BioProviderHttpResponse,
    ) -> None:
        if file_format == "pdb":
            valid = any(
                line.startswith(("ATOM", "HETATM", "HEADER", "TITLE"))
                for line in content.splitlines()
            )
        else:
            valid = (
                content.lstrip().startswith(f"data_{pdb_id}")
                or "\n_atom_site." in content
            )
        if valid:
            return
        raise PipelineSdkFailure(
            error_type="provider_invalid_request",
            message="RCSB returned content that does not look like the requested structure format.",
            hint="Check the PDB id and requested format before retrying.",
            stage="provider_response_validation",
            retryable=False,
            sdk_method="rcsb_pdb.download_structure",
            details={
                "provider": "rcsb_pdb",
                "pdb_id": pdb_id,
                "format": file_format,
                "status_code": response.status_code,
                "body_excerpt": _scrub_provider_text(content[:500]),
                "response_digest": _sha256_text(content),
            },
        )

    def _bounded_batch_size(self, value: int | None, *, sdk_method: str) -> int:
        if value is None:
            return self.config.batch_size_cap
        if isinstance(value, bool) or not isinstance(value, int):
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="UniProt batch_size must be an exact integer.",
                hint="Retry with batch_size omitted or set to a positive integer.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"batch_size": value},
            )
        if value <= 0 or value > self.config.batch_size_cap:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="UniProt batch_size must be positive and within the S13 provider cap.",
                hint="Retry with batch_size between 1 and 100.",
                stage="provider_request_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"batch_size": value, "limit": self.config.batch_size_cap},
            )
        return value

    def _uniprot_fields(self, fields: tuple[str, ...]) -> list[str]:
        identity_fields = [
            "accession",
            "id",
            "sequence",
            "reviewed",
            "sequence_version",
            "version",
        ]
        default_fields = [
            *identity_fields,
            "protein_name",
            "organism_name",
            "length",
        ]
        allowed = {
            "accession",
            "id",
            "protein_name",
            "organism_name",
            "length",
            "sequence",
            "reviewed",
            "sequence_version",
            "version",
            "gene_names",
            "xref_pfam",
        }
        aliases = {"taxonomy": "organism_name", "organism": "organism_name"}
        selected = list(identity_fields)
        for field in fields:
            normalized = aliases.get(field, field)
            if normalized in allowed and normalized not in selected:
                selected.append(normalized)
        return selected if fields else default_fields

    def _next_link(self, headers: dict[str, str]) -> str | None:
        link = headers.get("Link") or headers.get("link")
        if not link:
            return None
        for part in str(link).split(","):
            if 'rel="next"' not in part:
                continue
            match = re.search(r"<([^>]+)>", part)
            if match:
                candidate = match.group(1)
                try:
                    parsed = urllib_parse.urlparse(candidate)
                    port = parsed.port
                except ValueError as exc:
                    raise self._uniprot_schema_failure(
                        "UniProt pagination returned a malformed next link.",
                        details={"next_link_digest": _sha256_text(candidate)},
                    ) from exc
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != "rest.uniprot.org"
                    or parsed.username is not None
                    or parsed.password is not None
                    or port not in {None, 443}
                    or parsed.path != "/uniprotkb/search"
                    or parsed.fragment
                ):
                    raise self._uniprot_schema_failure(
                        "UniProt pagination left the pinned HTTPS search endpoint.",
                        details={
                            "next_link_digest": _sha256_text(candidate),
                            "expected_endpoint": (
                                "https://rest.uniprot.org/uniprotkb/search"
                            ),
                        },
                    )
                return candidate
        return None

    def _parse_fasta_records(self, fasta: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        sequence_lines: list[str] = []
        for line in fasta.splitlines():
            if line.startswith(">"):
                if current is not None:
                    current["sequence"] = "".join(sequence_lines).upper()
                    current["length"] = len(current["sequence"])
                    current["fasta_record"] = (
                        f">{current['description']}\n"
                        + "\n".join(sequence_lines)
                        + "\n"
                    )
                    records.append(current)
                header = line[1:].strip()
                accession = header.split(maxsplit=1)[0] if header else "unknown"
                current = {"accession": accession, "description": header}
                sequence_lines = []
            elif current is not None:
                sequence_lines.append(line.strip())
        if current is not None:
            current["sequence"] = "".join(sequence_lines).upper()
            current["length"] = len(current["sequence"])
            current["fasta_record"] = (
                f">{current['description']}\n" + "\n".join(sequence_lines) + "\n"
            )
            records.append(current)
        return records

    def _resolve_ncbi_records(
        self,
        *,
        requested_accessions: tuple[str, ...],
        records: list[dict[str, Any]],
        response: BioProviderHttpResponse,
    ) -> list[dict[str, Any]]:
        request_lookup = {
            accession.upper(): accession for accession in requested_accessions
        }
        resolved_by_request: dict[str, dict[str, Any]] = {}
        unexpected: list[str] = []
        duplicate_requests: list[str] = []
        duplicate_resolved: list[str] = []
        seen_resolved: set[str] = set()

        for record in records:
            provider_accession, normalized_accession, resolution_rule = (
                self._ncbi_record_identity(str(record.get("description") or ""))
            )
            requested = request_lookup.get(normalized_accession.upper())
            if requested is None:
                unexpected.append(provider_accession)
                continue
            if requested in resolved_by_request:
                duplicate_requests.append(requested)
                continue
            if provider_accession in seen_resolved:
                duplicate_resolved.append(provider_accession)
                continue
            sequence = str(record.get("sequence") or "")
            if not sequence or not re.fullmatch(r"[A-Z*.-]+", sequence):
                raise PipelineSdkFailure(
                    error_type="provider_schema_drift",
                    message="NCBI returned an empty or malformed protein sequence.",
                    hint="Inspect the sealed FASTA response before retrying.",
                    stage="provider_response_validation",
                    retryable=False,
                    sdk_method="bio.ncbi_fetch_proteins",
                    details={
                        "provider": "ncbi",
                        "requested_accession": requested,
                        "resolved_accession": provider_accession,
                        "response_digest": response.body_digest,
                    },
                )
            fasta_record = str(record["fasta_record"])
            resolved_by_request[requested] = {
                **record,
                "requested_accession": requested,
                "resolved_accession": provider_accession,
                "normalized_resolved_accession": normalized_accession,
                "resolution_rule": resolution_rule,
                "sequence_digest": _sha256_text(sequence),
                "fasta_record_digest": _sha256_text(fasta_record),
            }
            seen_resolved.add(provider_accession)

        missing = [
            accession
            for accession in requested_accessions
            if accession not in resolved_by_request
        ]
        if missing or unexpected or duplicate_requests or duplicate_resolved:
            raise PipelineSdkFailure(
                error_type="provider_identity_mismatch",
                message="NCBI did not return a one-to-one requested-to-resolved protein identity set.",
                hint="Do not use the response until every requested accession resolves exactly once.",
                stage="provider_response_validation",
                retryable=False,
                sdk_method="bio.ncbi_fetch_proteins",
                details={
                    "provider": "ncbi",
                    "requested_accessions": list(requested_accessions),
                    "missing_accessions": missing,
                    "unexpected_resolved_accessions": unexpected,
                    "duplicate_requested_mappings": sorted(set(duplicate_requests)),
                    "duplicate_resolved_accessions": sorted(set(duplicate_resolved)),
                    "record_count": len(records),
                    "response_digest": response.body_digest,
                },
            )
        return [resolved_by_request[accession] for accession in requested_accessions]

    def _ncbi_record_identity(self, header: str) -> tuple[str, str, str]:
        provider_accession = header.split(maxsplit=1)[0] if header else ""
        pdb_match = re.fullmatch(
            r"pdb\|(?P<pdb>[0-9A-Za-z]{4})\|(?P<chain>[0-9A-Za-z]+)",
            provider_accession,
            flags=re.IGNORECASE,
        )
        if pdb_match is not None:
            normalized = (
                f"{pdb_match.group('pdb').upper()}_{pdb_match.group('chain').upper()}"
            )
            return provider_accession, normalized, "ncbi_pdb_chain_pipe@1"
        namespaced_match = re.fullmatch(
            r"(?:ref|gb|emb|dbj)\|(?P<accession>[A-Za-z0-9_.-]+)\|?",
            provider_accession,
            flags=re.IGNORECASE,
        )
        if namespaced_match is not None:
            return (
                provider_accession,
                namespaced_match.group("accession"),
                "ncbi_sequence_namespace_pipe@1",
            )
        if re.fullmatch(r"[A-Za-z0-9_.-]+", provider_accession):
            return provider_accession, provider_accession, "ncbi_accession_token@1"
        raise PipelineSdkFailure(
            error_type="provider_schema_drift",
            message="NCBI FASTA header did not expose a supported protein identity.",
            hint="Inspect the sealed FASTA response before changing identity rules.",
            stage="provider_response_validation",
            retryable=False,
            sdk_method="bio.ncbi_fetch_proteins",
            details={
                "provider": "ncbi",
                "header_excerpt": _scrub_provider_text(header[:500]),
            },
        )

    def _normalize_uniprot_records(
        self,
        *,
        requested_accessions: tuple[str, ...],
        pages: list[dict[str, Any]],
        requests: list[dict[str, Any]],
        retrieved_at: str,
        source_sequence_identities: dict[str, dict[str, str]] | None,
        sequence_mismatch_choices: dict[str, str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not any(list(page.get("results") or []) for page in pages):
            return [], []
        release = self._uniprot_release(requests)
        release_date = self._uniprot_release_date(requests)
        requested_lookup = {
            accession.upper(): accession for accession in requested_accessions
        }
        if source_sequence_identities is not None and not isinstance(
            source_sequence_identities, dict
        ):
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="UniProt source sequence identities must be an accession-keyed object.",
                hint="Pass source_sequence_identities as accession to provenance/digest records.",
                stage="bio_input_validation",
                retryable=False,
                sdk_method="bio.uniprot_fetch",
            )
        if sequence_mismatch_choices is not None and not isinstance(
            sequence_mismatch_choices, dict
        ):
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="UniProt sequence mismatch choices must be an accession-keyed object.",
                hint="Use the explicit value 'accept_uniprot' only after inspecting both digests.",
                stage="bio_input_validation",
                retryable=False,
                sdk_method="bio.uniprot_fetch",
            )
        normalized_sources: dict[str, dict[str, str]] = {}
        for raw_accession, raw_identity in (source_sequence_identities or {}).items():
            lookup_key = str(raw_accession).strip().upper()
            requested_accession = requested_lookup.get(lookup_key)
            if requested_accession is None or not isinstance(raw_identity, dict):
                raise PipelineSdkFailure(
                    error_type="provider_invalid_request",
                    message="A source sequence identity does not map to one requested UniProt accession.",
                    hint="Remove stale source identities before retrying.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method="bio.uniprot_fetch",
                    details={"source_accession_key": str(raw_accession)},
                )
            identity = {
                "source_database": str(
                    raw_identity.get("source_database") or ""
                ).strip(),
                "source_accession": str(
                    raw_identity.get("source_accession") or ""
                ).strip(),
                "sequence_digest": str(
                    raw_identity.get("sequence_digest") or ""
                ).strip(),
            }
            if (
                not identity["source_database"]
                or not identity["source_accession"]
                or re.fullmatch(r"sha256:[0-9a-f]{64}", identity["sequence_digest"])
                is None
            ):
                raise PipelineSdkFailure(
                    error_type="provider_invalid_request",
                    message="A source sequence identity is incomplete or has a malformed digest.",
                    hint="Bind source database, source accession, and an exact SHA-256 sequence digest.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method="bio.uniprot_fetch",
                    details={"requested_accession": requested_accession},
                )
            normalized_sources[requested_accession] = identity
        normalized_choices: dict[str, str] = {}
        for raw_accession, raw_choice in (sequence_mismatch_choices or {}).items():
            requested_accession = requested_lookup.get(
                str(raw_accession).strip().upper()
            )
            choice = str(raw_choice).strip()
            if (
                requested_accession is None
                or requested_accession not in normalized_sources
                or choice != "accept_uniprot"
            ):
                raise PipelineSdkFailure(
                    error_type="provider_invalid_request",
                    message="A UniProt mismatch choice is stale or unsupported.",
                    hint="Use 'accept_uniprot' only for a supplied source identity with a proven digest mismatch.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method="bio.uniprot_fetch",
                    details={"requested_accession": str(raw_accession)},
                )
            normalized_choices[requested_accession] = choice
        records_by_request: dict[str, dict[str, Any]] = {}
        inactive_records_by_request: dict[str, dict[str, Any]] = {}
        primary_to_request: dict[str, str] = {}

        for page_number, page in enumerate(pages, start=1):
            page_results = page.get("results")
            if not isinstance(page_results, list):
                raise self._uniprot_schema_failure(
                    "UniProt response page did not contain a results list.",
                    details={"page": page_number},
                )
            page_request = requests[page_number - 1]
            page_response_digest = str(page_request["response_digest"])
            query_accession_start = int(page_request["query_accession_start"])
            query_accession_count = int(page_request["query_accession_count"])
            query_requested_accessions = set(
                requested_accessions[
                    query_accession_start : query_accession_start
                    + query_accession_count
                ]
            )
            for result_index, result in enumerate(page_results):
                if not isinstance(result, dict):
                    raise self._uniprot_schema_failure(
                        "UniProt result was not an object.",
                        details={"page": page_number, "result_index": result_index},
                    )
                primary_accession = (
                    str(result.get("primaryAccession") or "").strip().upper()
                )
                if not self._is_uniprot_accession(primary_accession):
                    raise self._uniprot_schema_failure(
                        "UniProt result did not contain a valid primary accession.",
                        details={
                            "page": page_number,
                            "result_index": result_index,
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                if result.get("entryType") == "Inactive":
                    requested_accession = requested_lookup.get(primary_accession)
                    if (
                        requested_accession is None
                        or requested_accession not in query_requested_accessions
                    ):
                        raise PipelineSdkFailure(
                            error_type="provider_identity_mismatch",
                            message=(
                                "A UniProt inactive identity did not exactly match one "
                                "accession from its producing query batch."
                            ),
                            hint=(
                                "Do not follow, replace, or infer an inactive identity; "
                                "inspect the sealed response and query-batch transcript."
                            ),
                            stage="provider_response_validation",
                            retryable=False,
                            sdk_method="bio.uniprot_fetch",
                            details={
                                "provider": "uniprot",
                                "primary_accession": primary_accession,
                                "query_batch_index": page_request["query_batch_index"],
                                "query_accession_start": query_accession_start,
                                "query_accession_count": query_accession_count,
                                "query_accessions_digest": page_request[
                                    "query_accessions_digest"
                                ],
                                "response_digest": page_response_digest,
                                "selection_required": False,
                            },
                        )
                    if (
                        requested_accession in records_by_request
                        or requested_accession in inactive_records_by_request
                    ):
                        raise PipelineSdkFailure(
                            error_type="provider_duplicate_identity",
                            message=(
                                "UniProt returned more than one record for one requested "
                                "accession."
                            ),
                            hint="Do not choose between active and inactive records implicitly.",
                            stage="provider_response_validation",
                            retryable=False,
                            sdk_method="bio.uniprot_fetch",
                            details={
                                "provider": "uniprot",
                                "requested_accession": requested_accession,
                                "response_digest": page_response_digest,
                            },
                        )
                    inactive_reason = result.get("inactiveReason")
                    extra_attributes = result.get("extraAttributes")
                    if (
                        not isinstance(inactive_reason, dict)
                        or not isinstance(extra_attributes, dict)
                        or "uniParcId" not in extra_attributes
                        or extra_attributes["uniParcId"]
                        != str(extra_attributes["uniParcId"]).strip()
                        or re.fullmatch(
                            r"UPI[0-9A-F]{10}",
                            str(extra_attributes.get("uniParcId") or "").strip(),
                        )
                        is None
                        or "sequence" in result
                        or "entryAudit" in result
                    ):
                        raise self._uniprot_schema_failure(
                            "UniProt inactive record did not expose a typed sequence-free identity.",
                            details={
                                "primary_accession": primary_accession,
                                "response_digest": page_response_digest,
                                "expected_entry_type": "Inactive",
                                "accepted_inactive_reason_types": [
                                    "DELETED",
                                    "MERGED",
                                ],
                            },
                        )
                    normalized_inactive_reason = (
                        self._normalize_uniprot_inactive_reason(
                            inactive_reason,
                            requested_accession=requested_accession,
                            primary_accession=primary_accession,
                            response_digest=page_response_digest,
                        )
                    )
                    identifier = str(result.get("uniProtkbId") or "").strip()
                    if (
                        not identifier
                        or result.get("uniProtkbId") != identifier
                        or any(ord(character) < 32 for character in identifier)
                    ):
                        raise self._uniprot_schema_failure(
                            "UniProt inactive record did not contain its identifier.",
                            details={
                                "primary_accession": primary_accession,
                                "response_digest": page_response_digest,
                            },
                        )
                    primary_owner = primary_to_request.get(primary_accession)
                    if (
                        primary_owner is not None
                        and primary_owner != requested_accession
                    ):
                        raise PipelineSdkFailure(
                            error_type="provider_identity_mismatch",
                            message=(
                                "Multiple requested accessions resolved to one UniProt "
                                "identity."
                            ),
                            hint="Do not infer or replace an inactive identity.",
                            stage="provider_response_validation",
                            retryable=False,
                            sdk_method="bio.uniprot_fetch",
                            details={
                                "provider": "uniprot",
                                "primary_accession": primary_accession,
                                "requested_accessions": [
                                    primary_owner,
                                    requested_accession,
                                ],
                                "selection_required": False,
                            },
                        )
                    raw_record_digest = _sha256_text(
                        _json_text(_sanitize_provider_value(result))
                    )
                    inactive_records_by_request[requested_accession] = {
                        "requested_accession": requested_accession,
                        "primary_accession": primary_accession,
                        "uniprot_identifier": identifier,
                        "entry_type": "Inactive",
                        "inactive_reason": normalized_inactive_reason,
                        "uniparc_id": str(extra_attributes["uniParcId"]).strip(),
                        "uniprot_release": release,
                        "uniprot_release_date": release_date,
                        "retrieved_at": retrieved_at,
                        "response_digest": page_response_digest,
                        "record_digest": raw_record_digest,
                        "provider_metadata": self._uniprot_metadata(result),
                    }
                    primary_to_request[primary_accession] = requested_accession
                    continue
                secondary_raw = result.get("secondaryAccessions") or []
                if not isinstance(secondary_raw, list) or any(
                    not isinstance(accession, str) for accession in secondary_raw
                ):
                    raise self._uniprot_schema_failure(
                        "UniProt secondary accessions were not a string list.",
                        details={
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                secondary_accessions = [
                    accession.strip().upper() for accession in secondary_raw
                ]
                matched_requests = [
                    requested_lookup[accession]
                    for accession in [primary_accession, *secondary_accessions]
                    if accession in requested_lookup
                ]
                matched_requests = list(dict.fromkeys(matched_requests))
                if (
                    len(matched_requests) != 1
                    or matched_requests[0] not in query_requested_accessions
                ):
                    raise PipelineSdkFailure(
                        error_type="provider_identity_mismatch",
                        message=(
                            "UniProt primary identity did not map to exactly one accession "
                            "from the query batch that produced the response page."
                        ),
                        hint=(
                            "Do not accept a cross-query provider response; inspect the "
                            "sealed response and query-batch transcript."
                        ),
                        stage="provider_response_validation",
                        retryable=False,
                        sdk_method="bio.uniprot_fetch",
                        details={
                            "provider": "uniprot",
                            "primary_accession": primary_accession,
                            "secondary_accessions": secondary_accessions,
                            "matched_requested_accessions": matched_requests,
                            "query_batch_index": page_request["query_batch_index"],
                            "query_accession_start": query_accession_start,
                            "query_accession_count": query_accession_count,
                            "query_accessions_digest": page_request[
                                "query_accessions_digest"
                            ],
                            "response_digest": page_response_digest,
                            "selection_required": True,
                        },
                    )
                requested_accession = matched_requests[0]
                sequence_payload = result.get("sequence")
                if not isinstance(sequence_payload, dict):
                    raise self._uniprot_schema_failure(
                        "UniProt result did not contain a sequence object.",
                        details={
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                sequence = str(sequence_payload.get("value") or "").strip().upper()
                if not sequence or not re.fullmatch(r"[A-Z*.-]+", sequence):
                    raise self._uniprot_schema_failure(
                        "UniProt result contained an empty or malformed protein sequence.",
                        details={
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                declared_length = sequence_payload.get("length")
                if declared_length is not None and (
                    isinstance(declared_length, bool)
                    or not isinstance(declared_length, int)
                    or declared_length != len(sequence)
                ):
                    raise self._uniprot_schema_failure(
                        "UniProt sequence length did not match its sequence bytes.",
                        details={
                            "primary_accession": primary_accession,
                            "declared_length": declared_length,
                            "actual_length": len(sequence),
                            "response_digest": page_response_digest,
                        },
                    )
                reviewed, entry_type = self._uniprot_reviewed_status(result)
                entry_audit = result.get("entryAudit")
                if not isinstance(entry_audit, dict):
                    raise self._uniprot_schema_failure(
                        "UniProt result did not contain entry version metadata.",
                        details={
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                entry_version = self._positive_uniprot_version(
                    entry_audit.get("entryVersion"),
                    field="entryVersion",
                    primary_accession=primary_accession,
                    response_digest=page_response_digest,
                )
                sequence_version = self._positive_uniprot_version(
                    entry_audit.get("sequenceVersion"),
                    field="sequenceVersion",
                    primary_accession=primary_accession,
                    response_digest=page_response_digest,
                )
                sequence_digest = _sha256_text(sequence)
                existing = records_by_request.get(requested_accession)
                if requested_accession in inactive_records_by_request:
                    raise PipelineSdkFailure(
                        error_type="provider_duplicate_identity",
                        message=(
                            "UniProt returned active and inactive records for one requested "
                            "accession."
                        ),
                        hint="Do not choose between conflicting provider records implicitly.",
                        stage="provider_response_validation",
                        retryable=False,
                        sdk_method="bio.uniprot_fetch",
                        details={
                            "provider": "uniprot",
                            "requested_accession": requested_accession,
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                if existing is not None:
                    if existing["sequence_digest"] != sequence_digest:
                        raise self._uniprot_sequence_conflict(
                            requested_accession=requested_accession,
                            identities=[
                                str(existing["primary_accession"]),
                                primary_accession,
                            ],
                            digests=[
                                str(existing["sequence_digest"]),
                                sequence_digest,
                            ],
                        )
                    raise PipelineSdkFailure(
                        error_type="provider_duplicate_identity",
                        message="UniProt returned a duplicate record for one requested accession.",
                        hint="Do not choose between duplicate provider records implicitly.",
                        stage="provider_response_validation",
                        retryable=False,
                        sdk_method="bio.uniprot_fetch",
                        details={
                            "provider": "uniprot",
                            "requested_accession": requested_accession,
                            "primary_accession": primary_accession,
                            "sequence_digest": sequence_digest,
                        },
                    )
                primary_owner = primary_to_request.get(primary_accession)
                if primary_owner is not None and primary_owner != requested_accession:
                    other = records_by_request.get(primary_owner)
                    if (
                        other is not None
                        and other["sequence_digest"] != sequence_digest
                    ):
                        raise self._uniprot_sequence_conflict(
                            requested_accession=requested_accession,
                            identities=[
                                primary_owner,
                                requested_accession,
                                primary_accession,
                            ],
                            digests=[str(other["sequence_digest"]), sequence_digest],
                        )
                    raise PipelineSdkFailure(
                        error_type="provider_identity_mismatch",
                        message="Multiple requested accessions resolved to one UniProt primary identity.",
                        hint="Select the intended primary identity explicitly.",
                        stage="provider_response_validation",
                        retryable=False,
                        sdk_method="bio.uniprot_fetch",
                        details={
                            "provider": "uniprot",
                            "primary_accession": primary_accession,
                            "requested_accessions": [
                                primary_owner,
                                requested_accession,
                            ],
                            "sequence_digest": sequence_digest,
                            "selection_required": True,
                        },
                    )
                identifier = str(result.get("uniProtkbId") or primary_accession).strip()
                if result.get("uniProtkbId") not in {None, identifier} or any(
                    ord(character) < 32 for character in identifier
                ):
                    raise self._uniprot_schema_failure(
                        "UniProt active record contained a malformed identifier.",
                        details={
                            "primary_accession": primary_accession,
                            "response_digest": page_response_digest,
                        },
                    )
                mapping_annotation = {
                    "annotation_type": "provider_identity_mapping",
                    "source_database": "requested_identifier",
                    "source_accession": requested_accession,
                    "target_database": "uniprotkb",
                    "target_accession": primary_accession,
                    "relationship": "resolves_to_primary_accession",
                    "identity_replaced": False,
                }
                mapping_annotations = [mapping_annotation]
                source_identity = normalized_sources.get(requested_accession)
                if source_identity is not None:
                    source_digest = source_identity["sequence_digest"]
                    choice = normalized_choices.get(requested_accession)
                    if source_digest != sequence_digest and choice != "accept_uniprot":
                        raise self._uniprot_sequence_conflict(
                            requested_accession=requested_accession,
                            identities=[
                                f"{source_identity['source_database']}:{source_identity['source_accession']}",
                                f"uniprotkb:{primary_accession}",
                            ],
                            digests=[source_digest, sequence_digest],
                            extra_details={
                                "source_identity": source_identity,
                                "allowed_choice": "accept_uniprot",
                            },
                        )
                    if source_digest == sequence_digest and choice is not None:
                        raise PipelineSdkFailure(
                            error_type="provider_invalid_request",
                            message="A UniProt mismatch choice was supplied but the sequence digests match.",
                            hint="Remove the stale mismatch choice and preserve the matching annotation.",
                            stage="bio_input_validation",
                            retryable=False,
                            sdk_method="bio.uniprot_fetch",
                            details={"requested_accession": requested_accession},
                        )
                    mapping_annotations.append(
                        {
                            "annotation_type": "cross_database_sequence_identity",
                            "source_database": source_identity["source_database"],
                            "source_accession": source_identity["source_accession"],
                            "source_sequence_digest": source_digest,
                            "target_database": "uniprotkb",
                            "target_accession": primary_accession,
                            "target_sequence_digest": sequence_digest,
                            "relationship": (
                                "sequence_digest_match"
                                if source_digest == sequence_digest
                                else "sequence_mismatch_explicitly_resolved"
                            ),
                            "explicit_choice": choice,
                            "identity_replaced": False,
                        }
                    )
                raw_record_digest = _sha256_text(
                    _json_text(_sanitize_provider_value(result))
                )
                records_by_request[requested_accession] = {
                    "requested_accession": requested_accession,
                    "primary_accession": primary_accession,
                    "uniprot_identifier": identifier,
                    "reviewed": reviewed,
                    "entry_type": entry_type,
                    "uniprot_release": release,
                    "uniprot_release_date": release_date,
                    "retrieved_at": retrieved_at,
                    "entry_version": entry_version,
                    "sequence_version": sequence_version,
                    "sequence_length": len(sequence),
                    "sequence_digest": sequence_digest,
                    "response_digest": page_response_digest,
                    "record_digest": raw_record_digest,
                    "mapping_annotations": mapping_annotations,
                    "provider_metadata": self._uniprot_metadata(result),
                    "fasta_record": f">{primary_accession} {identifier}\n{sequence}\n",
                }
                primary_to_request[primary_accession] = requested_accession

        missing = [
            accession
            for accession in requested_accessions
            if accession not in records_by_request
            and accession not in inactive_records_by_request
        ]
        if missing:
            raise PipelineSdkFailure(
                error_type="provider_identity_mismatch",
                message="UniProt did not resolve every requested accession.",
                hint="Do not continue until every HMMER candidate has one primary UniProt identity.",
                stage="provider_response_validation",
                retryable=False,
                sdk_method="bio.uniprot_fetch",
                details={
                    "provider": "uniprot",
                    "requested_accessions": list(requested_accessions),
                    "missing_accessions": missing,
                    "resolved_accessions": sorted(
                        {*records_by_request, *inactive_records_by_request}
                    ),
                },
            )
        source_identities_for_inactive = sorted(
            set(normalized_sources).intersection(inactive_records_by_request)
        )
        if source_identities_for_inactive:
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="A source sequence identity was supplied for an inactive UniProt record.",
                hint=(
                    "Remove source sequence assertions for inactive records; no sequence "
                    "comparison or replacement is allowed."
                ),
                stage="bio_input_validation",
                retryable=False,
                sdk_method="bio.uniprot_fetch",
                details={
                    "inactive_source_identity_accessions": source_identities_for_inactive
                },
            )
        return (
            [
                records_by_request[accession]
                for accession in requested_accessions
                if accession in records_by_request
            ],
            [
                inactive_records_by_request[accession]
                for accession in requested_accessions
                if accession in inactive_records_by_request
            ],
        )

    def _uniprot_release(self, requests: list[dict[str, Any]]) -> str | None:
        return self._consistent_uniprot_header(
            requests,
            header="x-uniprot-release",
            required=bool(requests),
        )

    def _uniprot_release_date(self, requests: list[dict[str, Any]]) -> str | None:
        return self._consistent_uniprot_header(
            requests,
            header="x-uniprot-release-date",
            required=False,
        )

    def _consistent_uniprot_header(
        self,
        requests: list[dict[str, Any]],
        *,
        header: str,
        required: bool,
    ) -> str | None:
        values: list[str] = []
        missing_pages: list[int] = []
        for page, request in enumerate(requests, start=1):
            headers = request.get("headers")
            if not isinstance(headers, dict):
                missing_pages.append(page)
                continue
            value = str(headers.get(header) or "").strip()
            if not value:
                missing_pages.append(page)
                continue
            values.append(value)
        if required and missing_pages:
            raise self._uniprot_schema_failure(
                f"UniProt response did not preserve the required {header} header.",
                details={"missing_pages": missing_pages, "header": header},
            )
        if not required and values and missing_pages:
            raise self._uniprot_schema_failure(
                f"UniProt response only partially preserved the optional {header} header.",
                details={"missing_pages": missing_pages, "header": header},
            )
        unique = sorted(set(values))
        if len(unique) > 1:
            raise self._uniprot_schema_failure(
                f"UniProt pagination crossed inconsistent {header} values.",
                details={"header": header, "values": unique},
            )
        return unique[0] if unique else None

    def _uniprot_reviewed_status(self, result: dict[str, Any]) -> tuple[bool, str]:
        raw_entry_type = result.get("entryType")
        entry_type = str(raw_entry_type or "").strip()
        reviewed_by_entry_type = {
            "UniProtKB reviewed (Swiss-Prot)": True,
            "UniProtKB unreviewed (TrEMBL)": False,
        }
        reviewed = reviewed_by_entry_type.get(entry_type)
        if (
            not isinstance(raw_entry_type, str)
            or raw_entry_type != entry_type
            or reviewed is None
            or "inactiveReason" in result
        ):
            raise self._uniprot_schema_failure(
                "UniProt active result did not expose one supported active entry type.",
                details={
                    "primary_accession": result.get("primaryAccession"),
                    "entry_type": entry_type,
                },
            )
        explicit = result.get("reviewed")
        if explicit is not None and (
            not isinstance(explicit, bool) or explicit is not reviewed
        ):
            raise self._uniprot_schema_failure(
                "UniProt reviewed flag disagreed with its active entry type.",
                details={
                    "primary_accession": result.get("primaryAccession"),
                    "entry_type": entry_type,
                },
            )
        return reviewed, entry_type

    def _positive_uniprot_version(
        self,
        value: Any,
        *,
        field: str,
        primary_accession: str,
        response_digest: str,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise self._uniprot_schema_failure(
                f"UniProt result did not expose a positive {field}.",
                details={
                    "primary_accession": primary_accession,
                    "field": field,
                    "value": value,
                    "response_digest": response_digest,
                },
            )
        return value

    def _uniprot_schema_failure(
        self,
        message: str,
        *,
        details: dict[str, Any],
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type="provider_schema_drift",
            message=message,
            hint="Inspect the sealed UniProt response before updating the parser.",
            stage="provider_response_validation",
            retryable=False,
            sdk_method="bio.uniprot_fetch",
            details={"provider": "uniprot", **details},
        )

    def _uniprot_sequence_conflict(
        self,
        *,
        requested_accession: str,
        identities: list[str],
        digests: list[str],
        extra_details: dict[str, Any] | None = None,
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type="provider_sequence_identity_conflict",
            message="UniProt mappings exposed conflicting sequence identities.",
            hint="Preserve both digests and explicitly select the intended sequence identity.",
            stage="provider_response_validation",
            retryable=False,
            sdk_method="bio.uniprot_fetch",
            details={
                "provider": "uniprot",
                "requested_accession": requested_accession,
                "identities": identities,
                "sequence_digests": digests,
                "selection_required": True,
                **dict(extra_details or {}),
            },
        )

    def _is_uniprot_accession(self, accession: str) -> bool:
        return (
            re.fullmatch(
                r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-[0-9]+)?",
                accession,
            )
            is not None
        )

    def _normalize_uniprot_inactive_reason(
        self,
        inactive_reason: dict[str, Any],
        *,
        requested_accession: str,
        primary_accession: str,
        response_digest: str,
    ) -> dict[str, Any]:
        reason_type = inactive_reason.get("inactiveReasonType")
        if reason_type == "DELETED":
            deleted_reason = inactive_reason.get("deletedReason")
            if (
                not isinstance(deleted_reason, str)
                or not deleted_reason.strip()
                or deleted_reason != deleted_reason.strip()
                or any(ord(character) < 32 for character in deleted_reason)
                or "mergeDemergeTo" in inactive_reason
            ):
                raise self._uniprot_schema_failure(
                    "UniProt DELETED identity did not contain one canonical deletion reason.",
                    details={
                        "primary_accession": primary_accession,
                        "response_digest": response_digest,
                        "inactive_reason_type": "DELETED",
                    },
                )
            return {
                "inactive_reason_type": "DELETED",
                "deleted_reason": deleted_reason,
            }
        if reason_type == "MERGED":
            raw_targets = inactive_reason.get("mergeDemergeTo")
            if (
                not isinstance(raw_targets, list)
                or not raw_targets
                or "deletedReason" in inactive_reason
            ):
                raise self._uniprot_schema_failure(
                    "UniProt MERGED identity did not contain replacement targets.",
                    details={
                        "primary_accession": primary_accession,
                        "response_digest": response_digest,
                        "inactive_reason_type": "MERGED",
                    },
                )
            targets: list[str] = []
            for target in raw_targets:
                if (
                    not isinstance(target, str)
                    or target != target.strip().upper()
                    or not self._is_uniprot_accession(target)
                    or target == requested_accession
                ):
                    raise self._uniprot_schema_failure(
                        "UniProt MERGED identity contained a malformed replacement target.",
                        details={
                            "primary_accession": primary_accession,
                            "response_digest": response_digest,
                            "inactive_reason_type": "MERGED",
                        },
                    )
                targets.append(target)
            if len(targets) != len(set(targets)):
                raise self._uniprot_schema_failure(
                    "UniProt MERGED identity contained duplicate replacement targets.",
                    details={
                        "primary_accession": primary_accession,
                        "response_digest": response_digest,
                        "inactive_reason_type": "MERGED",
                    },
                )
            return {
                "inactive_reason_type": "MERGED",
                "replacement_target_annotations": [
                    {
                        "annotation_type": "provider_inactive_replacement",
                        "source_database": "uniprotkb",
                        "source_accession": requested_accession,
                        "target_database": "uniprotkb",
                        "target_accession": target,
                        "relationship": "merged_into",
                        "identity_replaced": False,
                        "target_followed": False,
                    }
                    for target in sorted(targets)
                ],
            }
        raise self._uniprot_schema_failure(
            "UniProt inactive identity used an unsupported reason type.",
            details={
                "primary_accession": primary_accession,
                "response_digest": response_digest,
                "accepted_inactive_reason_types": ["DELETED", "MERGED"],
                "actual_inactive_reason_type": str(reason_type),
            },
        )

    def _uniprot_metadata(self, result: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(result)
        metadata.pop("sequence", None)
        return _sanitize_provider_value(metadata)

    def _extract_hmmer_job_id(self, body: str) -> str:
        return _extract_ebi_hmmer_job_id(body)

    def _poll_hmmer_job(
        self,
        job_id: str,
        *,
        page_size: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        deadline = time.monotonic() + self.config.hmmer_poll_timeout_seconds
        requests: list[dict[str, Any]] = []
        while True:
            poll = self.poll_hmmer_search(job_id=job_id, page_size=page_size)
            payload = poll.payload
            requests.append(self._hmmer_poll_request_record(poll))
            status = poll.status
            if status not in _HMMER_NONTERMINAL_JOB_STATUSES:
                return payload, requests
            if time.monotonic() >= deadline:
                raise PipelineSdkFailure(
                    error_type="provider_timeout",
                    message="EBI HMMER polling timed out.",
                    hint="Retry later or reduce the search scope.",
                    stage="provider_poll",
                    retryable=True,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "job_id": job_id,
                        "last_status": status,
                    },
                )
            self._sleep(self.config.hmmer_poll_interval_seconds)

    def _fetch_hmmer_result_pages(
        self,
        base: str,
        job_id: str,
        *,
        page_size: int,
        max_hits: int,
        expected_reported_hit_count: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        payloads: list[dict[str, Any]] = []
        requests: list[dict[str, Any]] = []
        declared_page_count: int | None = None
        page = 1
        while True:
            result_url = (
                f"{base}/result/{urllib_parse.quote(job_id)}?"
                + urllib_parse.urlencode(
                    {"format": "json", "page": page, "page_size": page_size}
                )
            )
            response = self._http_request(
                "GET",
                result_url,
                sdk_method="bio.hmmer_search",
                stage="provider_results",
            )
            try:
                payload = json.loads(response.body)
            except json.JSONDecodeError as exc:
                raise self._schema_failure(
                    "bio.hmmer_search",
                    "EBI HMMER result page was not JSON.",
                    response=response,
                ) from exc
            if not isinstance(payload, dict):
                raise self._schema_failure(
                    "bio.hmmer_search",
                    "EBI HMMER result page was not an object.",
                    response=response,
                )
            result = payload.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("hits"), list):
                raise self._schema_failure(
                    "bio.hmmer_search",
                    "EBI HMMER result page did not contain a hits list.",
                    response=response,
                )
            page_count = self._hmmer_page_count(payload.get("page_count"))
            if page_count is None:
                raise self._schema_failure(
                    "bio.hmmer_search",
                    "EBI HMMER result page did not declare page_count.",
                    response=response,
                )
            if declared_page_count is None:
                declared_page_count = page_count
            elif page_count != declared_page_count:
                raise PipelineSdkFailure(
                    error_type="provider_schema_drift",
                    message="EBI HMMER result page_count changed across pages.",
                    hint="Inspect the sealed result-page transcript before retrying.",
                    stage="provider_results",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "page": page,
                        "expected_page_count": declared_page_count,
                        "actual_page_count": page_count,
                        "response_digest": response.body_digest,
                    },
                )
            page_reported_hit_count = self._hmmer_reported_hit_count(
                payload,
                source=f"result_page:{page}",
            )
            if page_reported_hit_count != expected_reported_hit_count:
                raise PipelineSdkFailure(
                    error_type="provider_schema_drift",
                    message="EBI HMMER stats.nreported changed between terminal poll and result pages.",
                    hint="Inspect the sealed poll and result-page transcript before retrying.",
                    stage="provider_results",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "page": page,
                        "expected_reported_hit_count": expected_reported_hit_count,
                        "actual_reported_hit_count": page_reported_hit_count,
                        "response_digest": response.body_digest,
                    },
                )
            if page_count == 0 and (page != 1 or result["hits"]):
                raise PipelineSdkFailure(
                    error_type="provider_schema_drift",
                    message="EBI HMMER zero-page result was not an exact empty first page.",
                    hint="Inspect the sealed result response before retrying.",
                    stage="provider_results",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "page": page,
                        "page_count": page_count,
                        "hit_count": len(result["hits"]),
                        "response_digest": response.body_digest,
                    },
                )
            if 0 < page < page_count and len(result["hits"]) != page_size:
                raise PipelineSdkFailure(
                    error_type="provider_partial_result",
                    message="EBI HMMER returned a short non-terminal result page.",
                    hint=(
                        "Do not continue with a gapped pagination window; inspect the "
                        "sealed explicit result-page transcript."
                    ),
                    stage="provider_results",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "page": page,
                        "page_count": page_count,
                        "page_size": page_size,
                        "hit_count": len(result["hits"]),
                        "response_digest": response.body_digest,
                    },
                )
            payloads.append(payload)
            requests.append(
                {
                    "method": "GET",
                    "status_code": response.status_code,
                    "headers": _sanitize_provider_headers(response.headers),
                    "response_digest": response.body_digest,
                    "page": page,
                    "page_size": page_size,
                    "_raw_response": response,
                }
            )
            if self._hmmer_payload_hit_count(payloads) >= max_hits:
                return payloads, requests
            if page >= page_count:
                return payloads, requests
            page += 1

    def _hmmer_payload_hit_count(self, payloads: list[dict[str, Any]]) -> int:
        return sum(
            len(result["hits"])
            for payload in payloads
            if isinstance((result := payload.get("result")), dict)
            and isinstance(result.get("hits"), list)
        )

    def _hmmer_page_count(self, page_count: Any) -> int | None:
        if page_count is None or page_count == "":
            return None
        if isinstance(page_count, bool):
            value = None
        elif isinstance(page_count, int):
            value = page_count
        elif isinstance(page_count, str) and page_count.isdigit():
            value = int(page_count)
        else:
            value = None
        if value is not None and value >= 0:
            return value
        raise PipelineSdkFailure(
            error_type="provider_schema_drift",
            message="EBI HMMER result page_count was not a non-negative integer.",
            hint="Inspect provider_observation.json before retrying.",
            stage="provider_results",
            retryable=False,
            sdk_method="bio.hmmer_search",
            details={"provider": "ebi_hmmer", "page_count": str(page_count)},
        )

    def _hmmer_reported_hit_count(
        self,
        payload: dict[str, Any],
        *,
        source: str = "terminal_poll",
    ) -> int:
        result = payload.get("result")
        stats = result.get("stats") if isinstance(result, dict) else None
        raw_count = stats.get("nreported") if isinstance(stats, dict) else None
        if isinstance(raw_count, bool):
            count = None
        elif isinstance(raw_count, int):
            count = raw_count
        elif isinstance(raw_count, str) and raw_count.isdigit():
            count = int(raw_count)
        else:
            count = None
        if count is None or count < 0:
            raise PipelineSdkFailure(
                error_type="provider_schema_drift",
                message="EBI HMMER payload did not declare a non-negative stats.nreported.",
                hint="Inspect the sealed poll and result-page responses before retrying.",
                stage="provider_results",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={
                    "provider": "ebi_hmmer",
                    "source": source,
                    "nreported": str(raw_count),
                },
            )
        return count

    def _hmmer_hits_csv(self, hits: list[dict[str, Any]]) -> str:
        columns = (
            "target",
            "accession",
            "evalue",
            "score",
            "page",
            "hit_index",
            "evalue_numeric",
            "score_numeric",
            "raw_page_digest",
            "raw_hit_digest",
            "parsed_row_digest",
        )
        lines = [",".join(columns)]
        for hit in hits:
            lines.append(",".join(_csv_cell(hit.get(column, "")) for column in columns))
        return "\n".join(lines) + "\n"

    def _hmmer_result_hits(
        self,
        payload: dict[str, Any],
        *,
        page: int,
        database: str,
    ) -> list[dict[str, Any]]:
        result = payload.get("result")
        if not isinstance(result, dict):
            raise self._hmmer_schema_failure(
                "EBI HMMER result payload did not contain a result object.",
                details={"page": page, "database": database},
            )
        hits = result.get("hits")
        if not isinstance(hits, list) or any(not isinstance(hit, dict) for hit in hits):
            raise self._hmmer_schema_failure(
                "EBI HMMER result payload did not contain an object hit list.",
                details={"page": page, "database": database},
            )
        stats = result.get("stats")
        declared_database = payload.get("database")
        if declared_database is None and isinstance(stats, dict):
            declared_database = stats.get("database")
        if declared_database and str(declared_database).strip().lower() != database:
            raise self._hmmer_schema_failure(
                "EBI HMMER result database did not match the requested database.",
                details={
                    "page": page,
                    "expected_database": database,
                    "actual_database": str(declared_database),
                },
            )
        self._hmmer_page_count(payload.get("page_count"))
        return hits

    def _normalize_hmmer_hits(
        self,
        hits: list[tuple[int, str, dict[str, Any]]],
        *,
        database: str,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen_accessions: set[str] = set()
        for hit_index, (page, raw_page_digest, hit) in enumerate(hits):
            metadata = hit.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            if database == "refprot":
                accession_values: list[str] = []
                for value in (
                    metadata.get("uniprot_accession"),
                    metadata.get("accession"),
                    self._first_present(hit, "acc", "accession"),
                ):
                    accession_values.extend(
                        self._hmmer_uniprot_accession_candidates(value)
                    )
                unique_accessions = sorted(set(accession_values))
                if len(unique_accessions) != 1:
                    raise self._hmmer_schema_failure(
                        "EBI HMMER refprot hit did not expose one unambiguous UniProt accession.",
                        details={
                            "page": page,
                            "hit_index": hit_index,
                            "candidate_accessions": unique_accessions,
                            "raw_page_digest": raw_page_digest,
                        },
                    )
                accession = unique_accessions[0]
            else:
                accession = str(
                    self._first_present(hit, "acc", "accession")
                    or metadata.get("uniprot_accession")
                    or metadata.get("accession")
                    or self._first_present(hit, "name", "target")
                    or ""
                ).strip()
                if not accession:
                    raise self._hmmer_schema_failure(
                        "EBI HMMER hit did not expose a candidate identity.",
                        details={"page": page, "hit_index": hit_index},
                    )
            if accession in seen_accessions:
                raise PipelineSdkFailure(
                    error_type="provider_duplicate_identity",
                    message="EBI HMMER returned a duplicate candidate accession.",
                    hint="Do not collapse duplicate provider hits implicitly.",
                    stage="provider_results",
                    retryable=False,
                    sdk_method="bio.hmmer_search",
                    details={
                        "provider": "ebi_hmmer",
                        "database": database,
                        "accession": accession,
                        "page": page,
                    },
                )
            evalue_raw = self._first_present(hit, "evalue", "E")
            score_raw = self._first_present(hit, "score", "bitscore")
            evalue_numeric = self._hmmer_numeric(
                evalue_raw,
                field="evalue",
                page=page,
                hit_index=hit_index,
                nonnegative=True,
            )
            score_numeric = self._hmmer_numeric(
                score_raw,
                field="score",
                page=page,
                hit_index=hit_index,
                nonnegative=False,
            )
            target = str(
                metadata.get("uniprot_identifier")
                or metadata.get("identifier")
                or self._first_present(hit, "name", "target")
                or accession
            )
            raw_hit_digest = _sha256_text(_json_text(_sanitize_provider_value(hit)))
            row = {
                "target": target,
                "accession": accession,
                "evalue": str(evalue_raw),
                "score": str(score_raw),
                "page": page,
                "hit_index": hit_index,
                "evalue_numeric": evalue_numeric,
                "score_numeric": score_numeric,
                "raw_page_digest": raw_page_digest,
                "raw_hit_digest": raw_hit_digest,
            }
            row["parsed_row_digest"] = _sha256_text(_json_text(row))
            normalized.append(row)
            seen_accessions.add(accession)
        return normalized

    def _hmmer_uniprot_accession_candidates(self, value: Any) -> list[str]:
        if value is None:
            return []
        raw = str(value).strip().upper()
        if not raw:
            return []
        candidates = [raw, *(token for token in raw.split("|") if token)]
        return [
            candidate
            for candidate in dict.fromkeys(candidates)
            if self._is_uniprot_accession(candidate)
        ]

    def _hmmer_numeric(
        self,
        value: Any,
        *,
        field: str,
        page: int,
        hit_index: int,
        nonnegative: bool,
    ) -> str:
        if value is None or isinstance(value, bool):
            raise self._hmmer_schema_failure(
                f"EBI HMMER hit did not expose numeric {field}.",
                details={"page": page, "hit_index": hit_index, "field": field},
            )
        try:
            numeric = Decimal(str(value))
        except InvalidOperation as exc:
            raise self._hmmer_schema_failure(
                f"EBI HMMER hit {field} was not numeric.",
                details={"page": page, "hit_index": hit_index, "value": str(value)},
            ) from exc
        if not numeric.is_finite() or (nonnegative and numeric < 0):
            raise self._hmmer_schema_failure(
                f"EBI HMMER hit {field} was outside the accepted numeric domain.",
                details={"page": page, "hit_index": hit_index, "value": str(value)},
            )
        return str(numeric.normalize()) if numeric else "0"

    def _hmmer_schema_failure(
        self,
        message: str,
        *,
        details: dict[str, Any],
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type="provider_schema_drift",
            message=message,
            hint="Inspect the sealed EBI HMMER response before updating the parser.",
            stage="provider_results",
            retryable=False,
            sdk_method="bio.hmmer_search",
            details={"provider": "ebi_hmmer", **details},
        )

    def _first_present(self, payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return value
        return None

    def _raw_response_record(
        self,
        response: BioProviderHttpResponse,
        *,
        phase: str,
        ordinal: int,
    ) -> dict[str, Any]:
        return {
            "ordinal": ordinal,
            "phase": phase,
            "status_code": response.status_code,
            "headers": _sanitize_provider_headers(response.headers),
            "body_encoding": "base64",
            "body_base64": base64.b64encode(response.body_bytes).decode("ascii"),
            "body_digest": response.body_digest,
            "size_bytes": len(response.body_bytes),
        }

    def _raw_response_set(
        self,
        *,
        provider: str,
        operation: str,
        responses: list[tuple[str, BioProviderHttpResponse]],
    ) -> str:
        return _json_text(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": provider,
                "operation": operation,
                "responses": [
                    self._raw_response_record(
                        response,
                        phase=phase,
                        ordinal=ordinal,
                    )
                    for ordinal, (phase, response) in enumerate(responses, start=1)
                ],
            }
        )

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
        return BioArtifactDraft(
            relative_path=relative_path,
            kind=kind,
            title=title,
            content=content,
            format=format,
            metadata={
                "producer": "host_supervised_bio_provider",
                "provider": provider,
                "format": format,
                "response_digest": _sha256_text(content),
                "api_version": self.api_version,
                **metadata,
            },
        )


def _csv_cell(value: Any) -> str:
    text = str(value).replace('"', '""')
    if any(char in text for char in [",", '"', "\n", "\r"]):
        return f'"{text}"'
    return text


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
        content = self._fasta(sequences)
        membership_rows = "\n".join(
            ",".join(
                (
                    _csv_cell(f"cluster_{index}"),
                    _csv_cell(name),
                    _csv_cell(name),
                    "true",
                    "1.000000",
                    str(len(sequence)),
                )
            )
            for index, (name, sequence) in enumerate(sequences)
        )
        membership = ",".join(CDHIT_MEMBERSHIP_COLUMNS) + "\n" + membership_rows + "\n"
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
                    content=membership,
                    format="csv",
                    metadata={
                        "tool_name": "cd-hit",
                        "input_artifact_ids": [input_fasta.artifact_id],
                        "parameters": {"identity": identity, "mode": mode},
                        "retrieved_at": retrieved_at,
                        "membership_schema_id": CDHIT_MEMBERSHIP_SCHEMA_ID,
                        "membership_columns": list(CDHIT_MEMBERSHIP_COLUMNS),
                        "row_semantics": "one_member_per_row",
                    },
                    required_format="csv",
                    required_columns=CDHIT_MEMBERSHIP_COLUMNS,
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
        content = self._fasta(
            [
                (name, sequence + "-" * (index % 2))
                for index, (name, sequence) in enumerate(sequences)
            ]
        )
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
        hmm = (
            "HMMER3/f [OpenZyme fixture]\nNAME openzyme_fixture\nLENG "
            + str(max(len(item[1]) for item in sequences))
            + "\n//\n"
        )
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
        sequences = self._read_fasta(
            target_fasta, sdk_method="bio_tools.hmmer_search_cli"
        )
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
        rows = (
            "target,accession,evalue,score\n"
            + "\n".join(
                f"{name},{name},1e-20,{100 + index}.0"
                for index, (name, _) in enumerate(sequences)
            )
            + "\n"
        )
        log = "hmmer_search_cli completed\n" + (
            "x" * 512 if params.get("simulate") == "oversized_log" else ""
        )
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
                        "input_artifact_ids": [
                            hmm.artifact_id,
                            target_fasta.artifact_id,
                        ],
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
                        "input_artifact_ids": [
                            hmm.artifact_id,
                            target_fasta.artifact_id,
                        ],
                        "parameters": params,
                        "retrieved_at": retrieved_at,
                        "log_truncated": bool(
                            params.get("simulate") == "oversized_log"
                        ),
                    },
                    required_format="log",
                ),
            ),
        )

    def _ensure_tool_available(
        self, sdk_method: str, *, params: dict[str, Any]
    ) -> None:
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

    def _read_fasta(
        self, artifact: SessionArtifactRecord, *, sdk_method: str
    ) -> list[tuple[str, str]]:
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if metadata_format not in {
            "fasta",
            "fa",
            "faa",
        } and not artifact.relative_path.lower().endswith((".fasta", ".fa", ".faa")):
            raise self._failure(
                sdk_method,
                "invalid_fasta",
                f"Artifact {artifact.artifact_id!r} must be a FASTA sequence artifact.",
                "Provide a FASTA artifact generated by bio.* or bio_tools.*.",
                "bio_tools_input_validation",
                details={
                    "artifact_id": artifact.artifact_id,
                    "format": metadata_format,
                },
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
        if metadata_format != "hmm" and not artifact.relative_path.lower().endswith(
            ".hmm"
        ):
            raise self._failure(
                sdk_method,
                "invalid_hmm",
                f"Artifact {artifact.artifact_id!r} must be an HMM artifact.",
                "Provide an HMM artifact generated by bio_tools.hmmbuild.",
                "bio_tools_input_validation",
                details={
                    "artifact_id": artifact.artifact_id,
                    "format": metadata_format,
                },
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
                "source": "deterministic_bio_tools_fixture",
                "format": format,
                "tool_version": self.tool_version,
                "command_template": metadata.get("tool_name"),
                "sanitized_args": dict(metadata.get("parameters") or {}),
                "parameter_digest": parameter_digest,
                "resource_estimate": {
                    "cpu": 2,
                    "memory_gb": 4,
                    "max_runtime_minutes": 30,
                },
                "fixture_classification": "deterministic_fixture",
                "provider_status": "fixture_non_cutover",
                "tool_status": "fixture_non_cutover",
                "scientific_status": "fixture_non_cutover",
                "cutover_eligible": False,
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
            raise self._failure(
                "bio_tools.output",
                "invalid_fasta",
                f"Output {relative_path!r} is not FASTA.",
                "Regenerate the output.",
                "bio_tools_output_validation",
            )
        if required_format == "hmm" and not content.startswith("HMMER"):
            raise self._failure(
                "bio_tools.output",
                "invalid_hmm",
                f"Output {relative_path!r} is not HMMER format.",
                "Regenerate the output.",
                "bio_tools_output_validation",
            )
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
                "fixture_classification": "deterministic_fixture",
                "provider_status": "fixture_non_cutover",
                "tool_status": "fixture_non_cutover",
                "scientific_status": "fixture_non_cutover",
                "cutover_eligible": False,
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
        raise ValueError(
            f"{slot_name} artifact {requested!r} was not provided in required_artifact_ids"
        )
    if len(required_artifacts) > default_index:
        return required_artifacts[default_index]
    raise ValueError(
        f"{slot_name} requires an artifact id or required_artifact_ids[{default_index}]"
    )


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
        updated = tuple(
            replacement_records.get(artifact.artifact_id, artifact)
            for artifact in required_artifacts
        )
        return PreprocessResult(
            required_artifacts=updated, created_artifacts=tuple(created)
        )

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
        input_format = str(
            (artifact.metadata or {}).get("format")
            or source.suffix.lower().lstrip(".")
            or "unknown"
        ).lower()
        output_dir = self.output_root / session_id / invocation_id
        output_path = output_dir / f"{slot_name}.pdbqt"
        if operation == "prepare_receptor":
            prepared = prepare_receptor(source, output_path)
            provenance = {"source_storage_uri": artifact.storage_uri}
        elif slot_name == "ligand" and input_format in {"smiles", "smi"}:
            smiles = str((artifact.metadata or {}).get("smiles") or "").strip()
            if not smiles:
                smiles = (
                    source.read_text(encoding="utf-8", errors="replace")
                    .splitlines()[0]
                    .strip()
                )
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
            required_artifact_ids=tuple(
                str(value) for value in payload.get("required_artifact_ids", [])
            ),
            context_artifact_ids=tuple(
                str(value) for value in payload.get("context_artifact_ids", [])
            ),
            catalog_tool_id=str(payload.get("catalog_tool_id", "fpocket")),
            tool_inputs=None
            if payload.get("tool_inputs") is None
            else dict(payload.get("tool_inputs") or {}),
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
            "artifacts": [
                project_artifact_for_agent(artifact) for artifact in self.artifacts
            ],
            "parsed_result": None
            if self.parsed_result is None
            else self.parsed_result.to_dict(),
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
        return compile_hpc_tool_request(
            tool_id=handoff.catalog_tool_id,
            tool_inputs=tool_inputs,
            execution_mode=handoff.execution_mode,
            execution_goal=handoff.execution_goal,
            required_artifacts=resolved_required_artifacts,
            context_artifacts=resolved_context_artifacts,
            required_artifact_ids=handoff.required_artifact_ids,
            context_artifact_ids=handoff.context_artifact_ids,
            task_id=task.task_id,
        )


@dataclass(slots=True)
class DefaultExecutionResultParser:
    def parse_result(
        self,
        *,
        handoff: ExecutionHandoff,
        outcome: ExecutionOutcome,
        artifact_refs: tuple[SessionArtifactRecord, ...],
    ) -> ExecutionParsedResult:
        parsed = parse_execution_result(
            tool_id=handoff.catalog_tool_id,
            raw_result=outcome.raw_result,
            tool_inputs={}
            if handoff.tool_inputs is None
            else dict(handoff.tool_inputs),
            artifact_refs=artifact_refs,
        )
        return ExecutionParsedResult(
            result_summary=parsed.result_summary,
            structured_findings=sanitize_private_artifact_fields(
                parsed.structured_findings
            ),
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
    allow_bio_fixture_adapter: bool = False
    sandbox_workspace_root: Path | None = None
    artifact_blob_root: Path | None = None
    sandbox_host_call_context_factory: ExecutionHostCallContextFactory | None = None
    sandbox_process_registry: Any | None = None
    sandbox_process_signal_notifier: Any | None = None

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="execution",
            tool_names=(
                "execution.pipeline.start",
                "execution.pipeline.status",
            ),
            input_schema={
                "type": "object",
                "required": ["task_id", "code_artifact_id"],
            },
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

    def register_tools(self, registry: ToolRegistryProtocol) -> None:
        register_execution_tools(registry, self)

    def supports_durable_provider_lifecycle(
        self,
        operation: ControlledOperation,
    ) -> bool:
        adapter = self.bio_adapter
        return (
            f"{operation.sdk_module}.{operation.function_name}"
            == "bio.hmmer_search"
            and adapter is not None
            and all(
                callable(getattr(adapter, method_name, None))
                for method_name in (
                    "dispatch_hmmer_search",
                    "poll_hmmer_search",
                    "materialize_hmmer_search",
                )
            )
        )

    def execute_sandbox_adapter_operation(
        self,
        operation: ControlledOperation,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        method = f"{operation.sdk_module}.{operation.function_name}"
        self._verify_sandbox_adapter_input_artifacts(
            operation,
            sdk_method=method,
        )
        params = envelope.get("adapter_params")
        if not isinstance(params, dict):
            raise PipelineSdkFailure(
                error_type="adapter_execution_unavailable",
                message="S12 adapter operation is missing typed adapter params.",
                hint="Use the public openzyme_pipeline SDK so typed params are included in the S12 envelope.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        raw_durable_phase = envelope.get("_durable_provider_phase")
        raw_dispatch_receipt = envelope.get(
            "_durable_provider_dispatch_receipt"
        )
        raw_observation_receipts = envelope.get(
            "_durable_provider_observation_receipts"
        )
        if (
            raw_durable_phase is not None
            and (
                not isinstance(raw_durable_phase, str)
                or not raw_durable_phase
                or raw_durable_phase != raw_durable_phase.strip()
            )
        ):
            raise PipelineSdkFailure(
                error_type="provider_lifecycle_envelope_invalid",
                message="Durable provider phase identity is invalid.",
                hint="Preserve the execution and reject the malformed private envelope.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        if raw_dispatch_receipt is not None and not isinstance(
            raw_dispatch_receipt, dict
        ):
            raise PipelineSdkFailure(
                error_type="provider_lifecycle_envelope_invalid",
                message="Durable provider dispatch receipt is not an object.",
                hint="Preserve the execution and reject the malformed private envelope.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        if raw_observation_receipts is not None and (
            not isinstance(raw_observation_receipts, list)
            or any(not isinstance(item, dict) for item in raw_observation_receipts)
        ):
            raise PipelineSdkFailure(
                error_type="provider_lifecycle_envelope_invalid",
                message="Durable provider observation receipts are not a closed object list.",
                hint="Preserve the execution and reject the malformed private envelope.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        if raw_durable_phase is None and (
            raw_dispatch_receipt is not None
            or raw_observation_receipts is not None
        ):
            raise PipelineSdkFailure(
                error_type="provider_lifecycle_envelope_invalid",
                message="Durable provider receipts require an explicit phase.",
                hint="Preserve the execution and reject the malformed private envelope.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        if (
            operation.sdk_module in {"bio", "rcsb_pdb"}
            and operation.selected_backend == "provider_http"
        ):
            return self._execute_sandbox_bio_provider_operation(
                operation=operation,
                method=method,
                params=dict(params),
                frozen_provider_request_id=(
                    str(envelope.get("_durable_backend_handle_ref") or "") or None
                ),
                durable_provider_phase=raw_durable_phase,
                durable_provider_dispatch_receipt=(
                    dict(raw_dispatch_receipt)
                    if isinstance(raw_dispatch_receipt, dict)
                    else None
                ),
                durable_provider_observation_receipts=tuple(
                    dict(item)
                    for item in (raw_observation_receipts or [])
                ),
            )
        if operation.sdk_module == "bio_tools" and operation.selected_backend == "hpc":
            return self._execute_sandbox_bio_tool_hpc_operation(
                operation=operation,
                method=method,
                params=dict(params),
                reserved_runner_run_id=(
                    str(envelope.get("_durable_backend_handle_ref") or "") or None
                ),
            )
        if (
            operation.sdk_module == "structure_tools"
            and operation.selected_backend == "hpc"
        ):
            return self._execute_sandbox_structure_tool_hpc_operation(
                operation=operation,
                method=method,
                params=dict(params),
                reserved_runner_run_id=(
                    str(envelope.get("_durable_backend_handle_ref") or "") or None
                ),
            )
        raise PipelineSdkFailure(
            error_type="adapter_execution_unavailable",
            message=f"{method} does not have a Host adapter executor for selected backend {operation.selected_backend!r}.",
            hint="Implement the selected backend executor before treating this S15 operation as live-ready.",
            stage="adapter_route_dispatch",
            retryable=False,
            sdk_method=method,
            details={
                "operation_id": operation.operation_id,
                "route_policy_id": operation.route_policy_id,
                "selected_backend": operation.selected_backend,
            },
        )

    def _verify_sandbox_adapter_input_artifacts(
        self,
        operation: ControlledOperation,
        *,
        sdk_method: str,
    ) -> None:
        artifact_ids = tuple(operation.input_artifact_ids)
        artifact_digests = tuple(operation.input_artifact_digests)
        if len(artifact_ids) != len(artifact_digests):
            raise PipelineSdkFailure(
                error_type="artifact_digest_mismatch",
                message=(
                    f"{sdk_method} approved input artifact IDs and digests do not "
                    "have the same cardinality."
                ),
                hint="Recreate the controlled operation from current sealed artifact refs.",
                stage="adapter_input_integrity",
                retryable=False,
                sdk_method=sdk_method,
                details={"operation_id": operation.operation_id},
            )
        if not artifact_ids:
            return

        boundary = ArtifactBoundaryService(
            self.repositories,
            workspace_root=self.sandbox_workspace_root,
            blob_store_root=self.artifact_blob_root,
        )
        for artifact_id, approved_digest in zip(
            artifact_ids,
            artifact_digests,
            strict=True,
        ):
            artifact = self.repositories.artifacts.get(artifact_id)
            if artifact is None or artifact.session_id != operation.session_id:
                raise PipelineSdkFailure(
                    error_type="artifact_not_available",
                    message=(
                        f"{sdk_method} approved input artifact {artifact_id!r} is "
                        "not available in the operation session."
                    ),
                    hint="Use only current-session sealed artifacts in controlled operations.",
                    stage="adapter_input_integrity",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "operation_id": operation.operation_id,
                        "artifact_id": artifact_id,
                    },
                )
            metadata = dict(artifact.metadata or {})
            catalog_digest = str(
                metadata.get("content_digest")
                or metadata.get("tree_digest")
                or metadata.get("source_tree_digest")
                or ""
            )
            if not catalog_digest or catalog_digest != approved_digest:
                raise PipelineSdkFailure(
                    error_type="artifact_digest_mismatch",
                    message=(
                        f"{sdk_method} approved input digest does not match the "
                        f"catalog digest for artifact {artifact_id!r}."
                    ),
                    hint="Re-stage the current sealed artifact and request a fresh approval.",
                    stage="adapter_input_integrity",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "operation_id": operation.operation_id,
                        "artifact_id": artifact_id,
                        "approved_digest": approved_digest,
                        "catalog_digest": catalog_digest or None,
                    },
                )
            try:
                materialized = boundary.materialize(
                    session_id=operation.session_id,
                    sandbox_workspace_id=operation.sandbox_workspace_id,
                    artifact_id=artifact_id,
                    mode="readonly",
                )
            except ArtifactBoundaryError as exc:
                raise PipelineSdkFailure(
                    error_type=exc.error_code,
                    message=(
                        f"{sdk_method} refused an input whose sealed artifact "
                        "blob failed integrity verification."
                    ),
                    hint=exc.hint
                    or "Quarantine the corrupted blob and recreate the artifact before retrying.",
                    stage="adapter_input_integrity",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "operation_id": operation.operation_id,
                        "artifact_id": artifact_id,
                        **dict(exc.details),
                    },
                ) from exc
            if materialized.artifact_digest != approved_digest:
                raise PipelineSdkFailure(
                    error_type="artifact_digest_mismatch",
                    message=(
                        f"{sdk_method} materialized input digest differs from its "
                        "approved digest."
                    ),
                    hint="Recreate the controlled operation from current sealed artifact refs.",
                    stage="adapter_input_integrity",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "operation_id": operation.operation_id,
                        "artifact_id": artifact_id,
                        "approved_digest": approved_digest,
                        "materialized_digest": materialized.artifact_digest,
                    },
                )

    def fetch_sandbox_hpc_outputs(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "")
        sandbox_workspace_id = str(params.get("sandbox_workspace_id") or "")
        run_id = str(params.get("run_id") or "")
        if not session_id or not sandbox_workspace_id or not run_id:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message="hpc.fetch_outputs requires session, sandbox workspace, and run ids.",
                hint="Pass the run handle returned by an approved Host-supervised HPC placement operation.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={
                    "run_id": run_id,
                    "sandbox_workspace_id": sandbox_workspace_id,
                },
            )
        session = self._require_session(session_id)
        run = self.repositories.runs.get(run_id)
        if run is None or run.session_id != session_id:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message=f"HPC run {run_id!r} is not available in this session.",
                hint="Pass the run handle returned by the approved HPC placement operation.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={"run_id": run_id},
            )
        invocation = self.repositories.invocations.get(run.invocation_id)
        if invocation is None or invocation.session_id != session_id:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message=f"HPC run {run_id!r} is missing its supervising invocation.",
                hint="Retry through the public openzyme_pipeline bio_tools SDK.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={"run_id": run_id, "invocation_id": run.invocation_id},
            )
        if self._pipeline_sandbox_workspace_id(invocation) != sandbox_workspace_id:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message=f"HPC run {run_id!r} belongs to a different sandbox workspace.",
                hint="Fetch only the run handle returned in the current sandbox workspace.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={
                    "run_id": run_id,
                    "run_sandbox_workspace_id": self._pipeline_sandbox_workspace_id(
                        invocation
                    ),
                    "sandbox_workspace_id": sandbox_workspace_id,
                },
            )
        controlled_operation_id = str(params.get("operation_id") or "")
        controlled_operation_digest = str(params.get("operation_digest") or "")
        if bool(controlled_operation_id) != bool(controlled_operation_digest):
            raise PipelineSdkFailure(
                error_type="hpc_fetch_controlled_operation_identity_incomplete",
                message=(
                    "Durable HPC output fetch requires both operation_id and "
                    "operation_digest."
                ),
                hint="Retry from the canonical durable execution using its frozen identity.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
            )
        if controlled_operation_id:
            operation = self.repositories.controlled_operations.get(
                controlled_operation_id
            )
            workspace = self._require_hpc_workspace(
                params.get("hpc_workspace"), sdk_method="hpc.fetch_outputs"
            )
            expected_invocation_id = f"inv_sandbox_adapter_{controlled_operation_id}"
            if (
                operation is None
                or operation.session_id != session_id
                or operation.operation_digest != controlled_operation_digest
                or operation.sandbox_workspace_id != sandbox_workspace_id
                or operation.hpc_workspace_id != str(workspace["hpc_workspace_id"])
                or operation.selected_backend != "hpc"
                or invocation.invocation_id != expected_invocation_id
            ):
                raise PipelineSdkFailure(
                    error_type="hpc_fetch_controlled_operation_identity_drift",
                    message=(
                        "Durable HPC output fetch identity differs from its frozen "
                        "controlled operation."
                    ),
                    hint="Preserve the execution for exact reconciliation; do not bind these outputs.",
                    stage="hpc_fetch_validation",
                    retryable=False,
                    sdk_method="hpc.fetch_outputs",
                    details={
                        "operation_id": controlled_operation_id,
                        "run_id": run_id,
                        "invocation_id": invocation.invocation_id,
                    },
                )
        result = self._run_pipeline_hpc_fetch_outputs(
            session=session,
            invocation=invocation,
            params={
                "hpc_workspace": dict(params.get("hpc_workspace") or {}),
                "run_id": run_id,
                "controlled_operation_id": controlled_operation_id,
                "controlled_operation_digest": controlled_operation_digest,
            },
        )
        return {
            **result,
            "operation_id": params.get("operation_id"),
            "operation_digest": params.get("operation_digest"),
            "output_artifact_ids": list(result.get("registered_artifact_ids") or []),
        }

    def _execute_sandbox_bio_tool_hpc_operation(
        self,
        *,
        operation: ControlledOperation,
        method: str,
        params: dict[str, Any],
        reserved_runner_run_id: str | None = None,
    ) -> dict[str, Any]:
        route_policy = self._require_bio_tool_route_policy(method)
        if operation.route_policy_id != route_policy["route_policy_id"]:
            raise PipelineSdkFailure(
                error_type="toolchain_not_configured",
                message=f"{method} route policy does not match the approved S12 operation.",
                hint="Retry through the public SDK so route_policy_id and function name are consistent.",
                stage="bio_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "operation_id": operation.operation_id,
                    "operation_route_policy_id": operation.route_policy_id,
                    "expected_route_policy_id": route_policy["route_policy_id"],
                },
            )
        if operation.task_id is None:
            raise PipelineSdkFailure(
                error_type="adapter_execution_unavailable",
                message=f"{method} sandbox adapter operation is not bound to a task.",
                hint="Run bio_tools from a task-scoped sandbox teammate.",
                stage="adapter_context_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        session = self._require_session(operation.session_id)
        task = self._require_task(operation.session_id, operation.task_id)
        invocation, operation_key = self._sandbox_adapter_invocation(
            operation=operation,
            method=method,
            params=params,
        )
        run_handle = self._run_pipeline_bio_tool(
            session=session,
            task=task,
            invocation=invocation,
            method=method,
            params=params,
            reserved_runner_run_id=reserved_runner_run_id,
        )
        run_handle = {
            **run_handle,
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "operation_key": operation_key,
        }
        adapter_result = {
            "status": run_handle.get("status"),
            "backend_run_id": run_handle.get("runner_run_id")
            or run_handle.get("run_id"),
            "fetch_refs": [],
            "registered_artifact_ids": [],
            "output_artifact_ids": [],
            "bounded_summary": run_handle,
            "warnings": list(run_handle.get("warnings") or []),
        }
        self._emit(
            "sandbox.adapter_operation.hpc_submitted",
            {
                "operation_id": operation.operation_id,
                "sandbox_run_id": operation.sandbox_run_id,
                "operation": method,
                "run_id": run_handle.get("run_id"),
                "runner_run_id": run_handle.get("runner_run_id"),
            },
        )
        return {"adapter_result": adapter_result, "result_summary": run_handle}

    def _execute_sandbox_structure_tool_hpc_operation(
        self,
        *,
        operation: ControlledOperation,
        method: str,
        params: dict[str, Any],
        reserved_runner_run_id: str | None = None,
    ) -> dict[str, Any]:
        route_policy = self._require_structure_tool_route_policy(method)
        if operation.route_policy_id != route_policy["route_policy_id"]:
            raise PipelineSdkFailure(
                error_type="toolchain_not_configured",
                message=f"{method} route policy does not match the approved S12 operation.",
                hint="Retry through the public SDK so route_policy_id and function name are consistent.",
                stage="structure_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "operation_id": operation.operation_id,
                    "operation_route_policy_id": operation.route_policy_id,
                    "expected_route_policy_id": route_policy["route_policy_id"],
                },
            )
        if operation.task_id is None:
            raise PipelineSdkFailure(
                error_type="adapter_execution_unavailable",
                message=f"{method} sandbox adapter operation is not bound to a task.",
                hint="Run structure_tools from a task-scoped sandbox teammate.",
                stage="adapter_context_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        session = self._require_session(operation.session_id)
        task = self._require_task(operation.session_id, operation.task_id)
        invocation, operation_key = self._sandbox_adapter_invocation(
            operation=operation,
            method=method,
            params=params,
        )
        run_handle = self._run_pipeline_hpc(
            session=session,
            task=task,
            invocation=invocation,
            method=method,
            params=params,
            reserved_runner_run_id=reserved_runner_run_id,
        )
        run_handle = {
            **run_handle,
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "operation_key": operation_key,
        }
        adapter_result = {
            "status": run_handle.get("status"),
            "backend_run_id": run_handle.get("runner_run_id")
            or run_handle.get("run_id"),
            "fetch_refs": [],
            "registered_artifact_ids": [],
            "output_artifact_ids": [],
            "bounded_summary": run_handle,
            "warnings": list(run_handle.get("warnings") or []),
        }
        self._emit(
            "sandbox.adapter_operation.hpc_submitted",
            {
                "operation_id": operation.operation_id,
                "sandbox_run_id": operation.sandbox_run_id,
                "operation": method,
                "run_id": run_handle.get("run_id"),
                "runner_run_id": run_handle.get("runner_run_id"),
            },
        )
        return {"adapter_result": adapter_result, "result_summary": run_handle}

    def _sandbox_adapter_invocation(
        self,
        *,
        operation: ControlledOperation,
        method: str,
        params: dict[str, Any],
    ) -> tuple[EngineInvocation, str]:
        operation_key = self._pipeline_operation_key(method, params)
        sandbox_run = self.repositories.sandbox_runs.get(operation.sandbox_run_id)
        if (
            sandbox_run is None
            or sandbox_run.session_id != operation.session_id
            or sandbox_run.sandbox_workspace_id != operation.sandbox_workspace_id
        ):
            raise PipelineSdkFailure(
                error_type="sandbox_runtime_identity_unavailable",
                message="Sandbox adapter operation is not linked to its originating sandbox run.",
                hint="Execute the adapter only from a persisted sandbox run in the same session and workspace.",
                stage="adapter_context_validation",
                retryable=False,
                sdk_method=method,
                details={"sandbox_run_id": operation.sandbox_run_id},
            )
        runtime_identity = dict(sandbox_run.compatibility or {})
        required_identity_fields = _SANDBOX_IDENTITY_FIELDS
        missing_identity_fields = sorted(
            required_identity_fields - set(runtime_identity)
        )
        if missing_identity_fields:
            raise PipelineSdkFailure(
                error_type="sandbox_runtime_identity_unavailable",
                message="Originating sandbox run does not carry a complete immutable runtime identity.",
                hint="Create a new sandbox run after resolving the image and Pipeline SDK digests.",
                stage="adapter_context_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "sandbox_run_id": operation.sandbox_run_id,
                    "missing_fields": missing_identity_fields,
                },
            )
        invocation_id = f"inv_sandbox_adapter_{operation.operation_id}"
        input_id = f"eng_in_sandbox_adapter_{hashlib.sha256(invocation_id.encode('utf-8')).hexdigest()[:20]}"
        now = utc_now_iso()
        invocation = self.repositories.invocations.get(invocation_id)
        if invocation is None:
            invocation = EngineInvocation(
                invocation_id=invocation_id,
                session_id=operation.session_id,
                task_id=operation.task_id,
                lane_id=operation.lane_id,
                engine_name="sandbox_adapter",
                status=EngineInvocationStatus.RUNNING,
                input_ref=input_id,
                output_ref=None,
                approval_id=operation.approval_id,
                idempotency_key=f"sandbox-adapter:{operation.operation_id}",
                started_at=now,
            )
            self.repositories.invocations.save(invocation)
        pipeline = {
            "sandbox_workspace_id": operation.sandbox_workspace_id,
            "source_code_artifact_id": operation.source_snapshot_artifact_id,
            "source_code_digest": operation.source_snapshot_digest,
            "source_code_version": None,
            "code_digest": operation.source_snapshot_digest,
            "inputs": {
                "artifact_ids": list(operation.input_artifact_ids),
                "context_artifact_ids": [],
            },
            "approved_operation_keys": [operation_key],
            "completed_operations": {},
            "approval_id": operation.approval_id,
            "sandbox_status": "running",
            "adapter_operation_id": operation.operation_id,
            "sandbox_runtime_identity": runtime_identity,
        }
        document = self.repositories.engine_documents.get(input_id)
        if document is not None:
            current_payload = dict(document.payload)
            current_pipeline = dict(current_payload.get("pipeline") or {})
            completed = dict(current_pipeline.get("completed_operations") or {})
            approved = list(current_pipeline.get("approved_operation_keys") or [])
            if operation_key not in approved:
                approved.append(operation_key)
            pipeline["completed_operations"] = completed
            pipeline["approved_operation_keys"] = approved
            created_at = document.created_at
        else:
            created_at = now
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=operation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="execution_input",
                payload={
                    "task_id": operation.task_id,
                    "lane_id": operation.lane_id,
                    "pipeline": pipeline,
                },
                created_at=created_at,
                updated_at=now,
            )
        )
        return invocation, operation_key

    def _load_pipeline_source(
        self, *, session_id: str, code_artifact_id: str
    ) -> PipelineSource:
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
                source_metadata={
                    **source_metadata,
                    "source_code_digest": source_code_digest,
                },
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

    def _reload_pipeline_source(
        self, invocation: EngineInvocation, pipeline: dict[str, Any]
    ) -> PipelineSource:
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
        if (
            approved_digest is not None
            and str(approved_digest) != source.source_code_digest
        ):
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

    def _is_pipeline_dry_run_invocation(self, invocation: EngineInvocation) -> bool:
        if invocation.input_ref is None:
            return False
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            return False
        pipeline = document.payload.get("pipeline")
        return isinstance(pipeline, dict) and bool(pipeline.get("dry_run"))

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
            source = self._load_pipeline_source(
                session_id=session_id, code_artifact_id=str(code_artifact_id)
            )
        except PipelineSourceError as exc:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=str(
                    exc.source_metadata.get("actual_source_code_digest")
                    or exc.source_metadata.get("source_code_digest")
                    or exc.error_code
                ),
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
        bio_call_errors = self._pipeline_bio_call_errors(code)
        if bio_call_errors:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code="provider_output_path_invalid",
                message="Pipeline bio provider calls must declare output_dir under /workspace/output.",
                hint=f"Fix bio provider call(s): {bio_call_errors}",
                error_type="provider_output_path_invalid",
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
        try:
            sandbox_runtime_identity = self._resolve_sandbox_runtime_identity()
        except PipelineSdkFailure as exc:
            return self._fail_pipeline_start(
                session_id=session_id,
                task_id=task_id,
                code_digest=code_digest,
                inputs=pipeline_inputs,
                invocation_id=invocation_id,
                lane_id=lane_id,
                idempotency_key=idempotency_key,
                error_code=exc.error_type,
                message=exc.message,
                hint=exc.hint,
                error_type=exc.error_type,
                stage=exc.stage,
                retryable=exc.retryable,
                source_metadata=source_metadata,
            )
        execution_plan = self._build_execution_plan(
            code=code,
            code_digest=code_digest,
            inputs=pipeline_inputs,
            source_metadata=source_metadata,
            sandbox_runtime_identity=sandbox_runtime_identity,
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
            "sandbox_runtime_identity": sandbox_runtime_identity,
            "sdk_operation_log": execution_plan["operations"],
            "approved_operation_keys": [],
            "approved_plan_digest": None,
            "operation_call_counts": {},
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
                payload={
                    "task_id": task_id,
                    "lane_id": effective_lane_id,
                    "handoff": handoff_model.to_dict(),
                },
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "engine.invocation.started",
            {
                "invocation_id": invocation_id,
                "engine_name": self.descriptor.engine_name,
                "task_id": task_id,
            },
        )
        if approval is not None:
            return ExecutionStartResult(
                invocation=invocation, run=None, approval=approval
            )
        return self._submit_execution(
            session=session, task=task, invocation=invocation, handoff=handoff_model
        )

    def continue_after_approval(
        self, *, invocation_id: str, resolution: str | None = None
    ) -> ExecutionStartResult:
        invocation = self._require_invocation(invocation_id)
        session = self._require_session(invocation.session_id)
        task = self._require_task(invocation.session_id, str(invocation.task_id))
        input_payload = self._require_input_payload(invocation)
        pipeline_payload = dict(input_payload.get("pipeline") or {})
        if (
            pipeline_payload
            and "handoff" not in input_payload
            and self.sandbox_runner is not None
        ):
            if invocation.status.is_terminal:
                runs = self.repositories.runs.list_by_invocation(
                    invocation.session_id, invocation.invocation_id
                )
                artifacts: list[SessionArtifactRecord] = []
                for run in runs:
                    artifacts.extend(
                        self.repositories.artifacts.list_by_run(run.run_id)
                    )
                parsed = None
                if invocation.output_ref is not None:
                    output_document = self.repositories.engine_documents.get(
                        invocation.output_ref
                    )
                    if output_document is not None:
                        payload = dict(output_document.payload.get("pipeline") or {})
                        parsed = ExecutionParsedResult(
                            result_summary=str(
                                payload.get("terminal_summary")
                                or invocation.status.value
                            ),
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
            if (
                approval is not None
                and approval.status is ApprovalRequestStatus.APPROVED
            ):
                refreshed = self._require_invocation(invocation.invocation_id)
                running = self._replace_invocation(
                    refreshed, status=EngineInvocationStatus.RUNNING, finished_at=None
                )
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
            if (
                approval is not None
                and approval.status is ApprovalRequestStatus.PENDING
            ):
                return ExecutionStartResult(
                    invocation=invocation, run=None, approval=approval
                )
            cancelled = self._replace_invocation(
                invocation,
                status=EngineInvocationStatus.CANCELLED,
                finished_at=utc_now_iso(),
            )
            self.repositories.invocations.save(cancelled)
            self._emit(
                "execution.pipeline.failed",
                {
                    "invocation_id": cancelled.invocation_id,
                    "status": cancelled.status.value,
                },
            )
            return ExecutionStartResult(
                invocation=cancelled, run=None, approval=approval
            )
        handoff = self._load_handoff(invocation)
        approval = (
            None
            if invocation.approval_id is None
            else self.repositories.approvals.get(invocation.approval_id)
        )
        self._update_input_document(invocation, resolution=resolution)
        if approval is None:
            running = self._replace_invocation(
                invocation, status=EngineInvocationStatus.RUNNING, finished_at=None
            )
            self.repositories.invocations.save(running)
            return self._submit_execution(
                session=session, task=task, invocation=running, handoff=handoff
            )
        if approval.status is ApprovalRequestStatus.APPROVED:
            running = self._replace_invocation(
                invocation, status=EngineInvocationStatus.RUNNING, finished_at=None
            )
            self.repositories.invocations.save(running)
            self._emit(
                "engine.invocation.updated",
                {
                    "invocation_id": running.invocation_id,
                    "engine_name": running.engine_name,
                    "status": "running",
                },
            )
            return self._submit_execution(
                session=session, task=task, invocation=running, handoff=handoff
            )
        if approval.status is ApprovalRequestStatus.PENDING:
            waiting = self._replace_invocation(
                invocation,
                status=EngineInvocationStatus.WAITING_APPROVAL,
                finished_at=None,
            )
            self.repositories.invocations.save(waiting)
            return ExecutionStartResult(invocation=waiting, run=None, approval=approval)
        cancelled = self._replace_invocation(
            invocation,
            status=EngineInvocationStatus.CANCELLED,
            finished_at=utc_now_iso(),
        )
        self.repositories.invocations.save(cancelled)
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": cancelled.invocation_id,
                "engine_name": cancelled.engine_name,
                "status": "cancelled",
            },
        )
        return ExecutionStartResult(invocation=cancelled, run=None, approval=approval)

    def get_pipeline_status(
        self,
        *,
        session_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        invocation = self._require_session_invocation(session_id, invocation_id)
        payload = invocation.to_dict()
        if invocation.status is EngineInvocationStatus.WAITING_APPROVAL:
            approval = (
                None
                if invocation.approval_id is None
                else self.repositories.approvals.get(invocation.approval_id)
            )
            payload["approval"] = None if approval is None else approval.to_dict()
            return payload
        run = self.repositories.runs.get_by_invocation(
            invocation.session_id, invocation.invocation_id
        )
        if run is None:
            return payload
        if invocation.status.is_terminal and invocation.output_ref is not None:
            output_document = self.repositories.engine_documents.get(
                invocation.output_ref
            )
            payload["run"] = run.to_dict()
            payload["artifacts"] = [
                project_artifact_for_agent(artifact)
                for artifact in self.repositories.artifacts.list_by_invocation(
                    invocation.session_id, invocation.invocation_id
                )
            ]
            if output_document is not None:
                payload["output_payload"] = sanitize_private_artifact_fields(
                    output_document.payload
                )
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
        reconciled = self.reconcile_execution(
            session_id=session_id,
            invocation_id=invocation_id,
        )
        return reconciled.to_dict()

    def reconcile_execution(
        self,
        *,
        session_id: str,
        invocation_id: str,
    ) -> ExecutionStartResult:
        invocation = self._require_session_invocation(session_id, invocation_id)
        if invocation.status is EngineInvocationStatus.WAITING_APPROVAL:
            approval = (
                None
                if invocation.approval_id is None
                else self.repositories.approvals.get(invocation.approval_id)
            )
            return ExecutionStartResult(
                invocation=invocation, run=None, approval=approval
            )
        run = self._require_run(invocation)
        status = self.runner.get_execution_status(
            run_id=run.runner_run_id,
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
            remote_run_dir=run.remote_run_dir,
            summary=run.summary,
            created_at=run.created_at,
            updated_at=utc_now_iso(),
            finished_at=run.finished_at,
        )
        self.repositories.runs.save(updated_run)
        if not status.status.is_terminal:
            running = self._replace_invocation(
                invocation, status=EngineInvocationStatus.RUNNING, finished_at=None
            )
            self.repositories.invocations.save(running)
            return ExecutionStartResult(
                invocation=running,
                run=updated_run,
                approval=self._load_approval(running),
            )
        if status.status is RunStatus.SUCCEEDED:
            fetched = self.runner.fetch_execution_artifacts(
                run_id=run.runner_run_id,
            )
            self._emit(
                "execution.artifacts.fetched",
                {
                    "invocation_id": invocation.invocation_id,
                    "run_id": run.run_id,
                    "runner_run_id": run.runner_run_id,
                    "artifact_count": len(fetched.artifacts),
                    "relative_paths": [
                        artifact.relative_path for artifact in fetched.artifacts
                    ],
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
            remote_run_dir=run.remote_run_dir,
            raw_result=status.raw_result,
            artifacts=(),
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
                "source_code_artifact_id": pipeline_metadata.get(
                    "source_code_artifact_id"
                ),
                "source_code_digest": pipeline_metadata.get("source_code_digest"),
                "source_code_version": pipeline_metadata.get("source_code_version"),
            },
        )
        self._emit(
            "engine.invocation.started",
            {
                "invocation_id": invocation_id,
                "engine_name": self.descriptor.engine_name,
                "task_id": task_id,
            },
        )
        return self._run_pipeline_supervisor(
            session=session, task=task, invocation=invocation, code=code
        )

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
                f"Operations: {[item.get('operation') for item in plan.get('operations', [])]}"
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
            {
                "invocation_id": invocation_id,
                "engine_name": self.descriptor.engine_name,
                "task_id": task_id,
            },
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
        artifact_ids = tuple(
            str(value) for value in pipeline_inputs.get("artifact_ids") or []
        )
        context_ids = tuple(
            str(value) for value in pipeline_inputs.get("context_artifact_ids") or []
        )
        sandbox_inputs = self._resolve_artifacts(
            session.session_id, (*artifact_ids, *context_ids)
        )
        if self.sandbox_runner is None:
            raise RuntimeError("pipeline sandbox runner is not configured")
        expected_runtime_identity = dict(
            (pipeline.get("execution_plan") or {}).get("sandbox_runtime_identity") or {}
        )
        try:
            current_runtime_identity = self._resolve_sandbox_runtime_identity()
        except PipelineSdkFailure as exc:
            return self._finalize_pipeline_sdk_failure(
                invocation=invocation, failure=exc
            )
        if current_runtime_identity != expected_runtime_identity:
            return self._finalize_pipeline_sdk_failure(
                invocation=invocation,
                failure=PipelineSdkFailure(
                    error_type="sandbox_runtime_identity_drift",
                    message="Sandbox image or pipeline SDK identity changed after plan creation.",
                    hint="Create and approve a new execution plan for the current immutable runtime identity.",
                    stage="sandbox_preflight",
                    retryable=False,
                    details={
                        "expected_runtime_identity_digest": expected_runtime_identity.get(
                            "runtime_identity_digest"
                        ),
                        "current_runtime_identity_digest": current_runtime_identity.get(
                            "runtime_identity_digest"
                        ),
                    },
                ),
            )
        try:
            outcome = self.sandbox_runner.run_pipeline(
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                code=code,
                inputs=sandbox_inputs,
                control_handler=lambda method, params: (
                    self._handle_pipeline_sdk_call_in_owned_scope(
                        session=session,
                        task=task,
                        invocation_id=invocation.invocation_id,
                        method=method,
                        params=params,
                    )
                ),
                expected_runtime_identity=expected_runtime_identity,
            )
        except PipelineApprovalRequired as exc:
            waiting = (
                self.repositories.invocations.get(invocation.invocation_id)
                or invocation
            )
            return ExecutionStartResult(
                invocation=waiting, run=None, approval=exc.approval
            )
        except PipelineSdkFailure as exc:
            return self._finalize_pipeline_sdk_failure(
                invocation=invocation, failure=exc
            )
        except Exception as exc:
            raise RuntimeError(
                f"pipeline sandbox raised {type(exc).__name__}: {exc}"
            ) from exc
        waiting = self.repositories.invocations.get(invocation.invocation_id)
        if (
            waiting is not None
            and waiting.status is EngineInvocationStatus.WAITING_APPROVAL
        ):
            return ExecutionStartResult(
                invocation=waiting, run=None, approval=self._load_approval(waiting)
            )
        return self._finalize_pipeline_terminal(invocation=invocation, outcome=outcome)

    def _resolve_sandbox_runtime_identity(self) -> dict[str, str]:
        if self.sandbox_runner is None or not hasattr(self.sandbox_runner, "preflight"):
            raise PipelineSdkFailure(
                error_type="sandbox_runtime_identity_unavailable",
                message="Execution pipeline sandbox runtime identity is unavailable.",
                hint="Configure a sandbox runner that resolves immutable image and SDK digests.",
                stage="sandbox_preflight",
                retryable=False,
            )
        preflight = self.sandbox_runner.preflight()
        if not preflight.ok:
            raise PipelineSdkFailure(
                error_type="sandbox_preflight_failed",
                message=str(preflight.message or "pipeline sandbox preflight failed"),
                hint="Install and register the approved immutable sandbox image and pipeline SDK.",
                stage="sandbox_preflight",
                retryable=False,
            )
        try:
            return validate_closed_sandbox_runtime_identity(
                getattr(preflight, "runtime_identity", None)
            )
        except ValueError as exc:
            raise PipelineSdkFailure(
                error_type=(
                    "sandbox_runtime_identity_unavailable"
                    if str(exc) == "missing"
                    else "sandbox_runtime_identity_invalid"
                ),
                message="Sandbox preflight did not return one closed immutable runtime identity.",
                hint="Re-resolve the image and SDK identities; do not reuse stale preflight metadata.",
                stage="sandbox_preflight",
                retryable=False,
            ) from exc

    def _handle_pipeline_sdk_call_in_owned_scope(
        self,
        *,
        session: Any,
        task: Any,
        invocation_id: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        context_factory = self.sandbox_host_call_context_factory
        if context_factory is None:
            return self._handle_pipeline_sdk_call(
                session=session,
                task=task,
                invocation_id=invocation_id,
                method=method,
                params=params,
            )
        # Podman serves SDK control requests from its control-server thread. A
        # sqlite3 connection created by the outer engine thread is deliberately
        # thread-affine, so every callback gets a fresh connection-owned engine.
        # This is not a UoW: provider/runner calls below must never sit inside a
        # long SQLite transaction.
        with context_factory(
            session_id=session.session_id,
            invocation_id=invocation_id,
        ) as host_context:
            scoped_engine = replace(
                self,
                repositories=host_context.repositories,
                sandbox_host_call_context_factory=None,
            )
            scoped_session = scoped_engine._require_session(session.session_id)
            scoped_task = scoped_engine._require_task(
                scoped_session.session_id,
                task.task_id,
            )
            return scoped_engine._handle_pipeline_sdk_call(
                session=scoped_session,
                task=scoped_task,
                invocation_id=invocation_id,
                method=method,
                params=params,
            )

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
        if method == "s10.controlled_operation":
            return self._run_pipeline_controlled_operation(
                session=session,
                task=task,
                invocation=invocation,
                envelope=params,
            )
        if method in {
            "preprocess.convert_format",
            "preprocess.prepare_receptor",
            "preprocess.prepare_ligand",
            "preprocess.smiles_to_3d",
        }:
            return self._run_pipeline_preprocess(
                session=session, invocation=invocation, method=method, params=params
            )
        if method in BIO_PROVIDER_ROUTE_POLICY_IDS:
            return self._run_pipeline_bio(
                session=session, invocation=invocation, method=method, params=params
            )
        if method in {
            "bio_tools.cdhit",
            "bio_tools.mafft",
            "bio_tools.hmmbuild",
            "bio_tools.hmmalign",
            "bio_tools.hmmer_search_cli",
        }:
            return self._run_pipeline_bio_tool(
                session=session,
                task=task,
                invocation=invocation,
                method=method,
                params=params,
            )
        if method == "hpc.workspace":
            return self._run_pipeline_hpc_workspace(
                invocation=invocation, params=params
            )
        if method == "hpc.stage_artifact":
            return self._run_pipeline_hpc_stage_artifact(
                session=session, invocation=invocation, params=params
            )
        if method == "hpc.fetch_outputs":
            return self._run_pipeline_hpc_fetch_outputs(
                session=session, invocation=invocation, params=params
            )
        if method in {"structure_tools.fpocket", "docking.vina"}:
            return self._run_pipeline_hpc(
                session=session,
                task=task,
                invocation=invocation,
                method=method,
                params=params,
            )
        if method == "run.wait":
            run = self.repositories.runs.get(str(params["run_id"]))
            if run is None:
                raise ValueError(f"run {params['run_id']!r} does not exist")
            return run.to_dict()
        if method == "run.fetch_artifacts":
            return [
                self._sandbox_safe_artifact(artifact)
                for artifact in self.repositories.artifacts.list_by_run(
                    str(params["run_id"])
                )
            ]
        raise ValueError(f"unsupported SDK operation {method!r}")

    def _run_pipeline_controlled_operation(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        envelope: dict[str, Any],
    ) -> Any:
        route_policy_id = str(envelope.get("route_policy_id") or "")
        policy = dict(S12_ROUTE_POLICIES.get(route_policy_id) or {})
        if not policy:
            raise PipelineSdkFailure(
                error_type="route_policy_missing",
                message="S12 controlled operation route policy is not registered.",
                hint="Use a public SDK function with a registered static route policy.",
                stage="adapter_route_dispatch",
                retryable=False,
                sdk_method="s10.controlled_operation",
                details={"route_policy_id": route_policy_id},
            )
        sdk_module = str(envelope.get("sdk_module") or "")
        function_name = str(envelope.get("function_name") or "")
        if sdk_module != policy.get("sdk_module") or function_name != policy.get(
            "function_name"
        ):
            raise PipelineSdkFailure(
                error_type="adapter_schema_incompatible",
                message="SDK module/function does not match the selected route policy.",
                hint="Retry through the public SDK so route_policy_id and function name are consistent.",
                stage="adapter_route_dispatch",
                retryable=False,
                sdk_method="s10.controlled_operation",
                details={
                    "route_policy_id": route_policy_id,
                    "sdk_module": sdk_module,
                    "function_name": function_name,
                },
            )
        adapter_params = envelope.get("params")
        if not isinstance(adapter_params, dict):
            raise PipelineSdkFailure(
                error_type="invalid_tool_arguments",
                message="S12 controlled operation requires typed params.",
                hint="Use the public openzyme_pipeline SDK so typed adapter params are included.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method="s10.controlled_operation",
            )
        params_digest = str(envelope.get("params_digest") or "")
        actual_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    adapter_params, sort_keys=True, separators=(",", ":"), default=str
                ).encode("utf-8")
            ).hexdigest()
        )
        if actual_digest != params_digest:
            raise PipelineSdkFailure(
                error_type="adapter_params_digest_mismatch",
                message="S12 controlled operation params do not match params_digest.",
                hint="Do not mutate SDK params after computing the S12 envelope digest.",
                stage="adapter_input_validation",
                retryable=False,
                sdk_method="s10.controlled_operation",
                details={
                    "params_digest": params_digest,
                    "actual_digest": actual_digest,
                },
            )
        if policy.get("status") != "ok":
            raise PipelineSdkFailure(
                error_type=str(
                    policy.get("error_code") or "operation_prerequisite_missing"
                ),
                message="S12 controlled operation route policy is not executable.",
                hint="Fix route policy prerequisites before submitting the controlled operation.",
                stage="adapter_route_dispatch",
                retryable=False,
                sdk_method=f"{sdk_module}.{function_name}",
                details={
                    "route_policy_id": route_policy_id,
                    "status": policy.get("status"),
                },
            )
        method = f"{sdk_module}.{function_name}"
        selected_backend = str(policy.get("selected_backend") or "")
        if (
            method in BIO_PROVIDER_ROUTE_POLICY_IDS
            and selected_backend == "provider_http"
        ):
            return self._run_pipeline_bio(
                session=session,
                invocation=invocation,
                method=method,
                params=dict(adapter_params),
            )
        if method in BIO_TOOL_ROUTE_POLICY_IDS and selected_backend == "hpc":
            return self._run_pipeline_bio_tool(
                session=session,
                task=task,
                invocation=invocation,
                method=method,
                params=dict(adapter_params),
            )
        if method in STRUCTURE_TOOL_ROUTE_POLICY_IDS and selected_backend == "hpc":
            return self._run_pipeline_hpc(
                session=session,
                task=task,
                invocation=invocation,
                method=method,
                params=dict(adapter_params),
            )
        raise PipelineSdkFailure(
            error_type="adapter_execution_unavailable",
            message=f"{method} does not have a Host adapter executor for selected backend {selected_backend!r}.",
            hint="Implement the selected backend executor before treating this operation as live-ready.",
            stage="adapter_route_dispatch",
            retryable=False,
            sdk_method=method,
            details={
                "route_policy_id": route_policy_id,
                "selected_backend": selected_backend,
            },
        )

    def _pipeline_sandbox_workspace_id(self, invocation: EngineInvocation) -> str:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        return str(
            pipeline.get("sandbox_workspace_id")
            or f"pipeline:{invocation.invocation_id}"
        )

    def _normalize_hpc_workspace_label(self, label: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-._")
        if not normalized or len(normalized) > 80 or normalized in {".", ".."}:
            raise PipelineSdkFailure(
                error_type="hpc_workspace_label_invalid",
                message=f"HPC workspace label {label!r} is invalid.",
                hint="Use a short label containing letters, numbers, '.', '_' or '-'.",
                stage="hpc_workspace_validation",
                retryable=False,
                sdk_method="hpc.workspace",
                details={"label": label},
            )
        return normalized

    def _validate_hpc_workspace_path(self, value: str, *, sdk_method: str) -> str:
        normalized = value.strip()
        path = PurePosixPath(normalized)
        forbidden_chars = (
            ";",
            "&",
            "|",
            "`",
            "$",
            "\\",
            "\n",
            "\r",
            "<",
            ">",
            "*",
            "?",
            "[",
            "]",
            "{",
            "}",
            "!",
        )
        if (
            not normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(char in normalized for char in forbidden_chars)
        ):
            raise PipelineSdkFailure(
                error_type="hpc_stage_path_invalid",
                message=f"HPC workspace path {value!r} is invalid.",
                hint="Use a normalized POSIX relative path without '..' or shell metacharacters.",
                stage="hpc_stage_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"workspace_path": value},
            )
        return path.as_posix()

    def _run_pipeline_hpc_workspace(
        self, *, invocation: EngineInvocation, params: dict[str, Any]
    ) -> dict[str, Any]:
        label = str(params.get("label") or "")
        normalized_label = self._normalize_hpc_workspace_label(label)
        sandbox_workspace_id = self._pipeline_sandbox_workspace_id(invocation)
        digest = hashlib.sha256(
            f"{sandbox_workspace_id}:{normalized_label}".encode("utf-8")
        ).hexdigest()[:16]
        return {
            "kind": "hpc_workspace",
            "hpc_workspace_id": f"hpcws_{digest}",
            "label": label,
            "normalized_label": normalized_label,
            "sandbox_workspace_id": sandbox_workspace_id,
            "placement_profile_id": "default",
        }

    def _require_hpc_workspace(self, value: Any, *, sdk_method: str) -> dict[str, Any]:
        if not isinstance(value, dict) or not value.get("hpc_workspace_id"):
            raise PipelineSdkFailure(
                error_type="hpc_workspace_forbidden",
                message=f"{sdk_method} requires an explicit hpc.workspace(...) placement.",
                hint="Create a workspace with hpc.workspace(label) and pass it as placement.",
                stage="hpc_placement_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        return dict(value)

    def _run_pipeline_hpc_stage_artifact(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        workspace = self._require_hpc_workspace(
            params.get("hpc_workspace"), sdk_method="hpc.stage_artifact"
        )
        artifact_id = str(params.get("artifact_id") or "")
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None or artifact.session_id != session.session_id:
            raise PipelineSdkFailure(
                error_type="hpc_workspace_forbidden",
                message=f"Artifact {artifact_id!r} is not available for staging in this session.",
                hint="Stage only catalog artifacts created or authorized in the current session.",
                stage="hpc_stage_validation",
                retryable=False,
                sdk_method="hpc.stage_artifact",
                details={"artifact_id": artifact_id},
            )
        workspace_relative_path = self._validate_hpc_workspace_path(
            str(params.get("workspace_path") or ""),
            sdk_method="hpc.stage_artifact",
        )
        artifact_digest = self._sealed_artifact_digest(
            artifact,
            sdk_method="hpc.stage_artifact",
        )
        hpc_workspace_id = str(workspace["hpc_workspace_id"])
        existing_stage = self._find_hpc_stage_ref(
            session_id=session.session_id,
            hpc_workspace_id=hpc_workspace_id,
            workspace_relative_path=workspace_relative_path,
        )
        if existing_stage is not None:
            existing_digest = str(existing_stage.get("artifact_digest") or "")
            if existing_digest != artifact_digest:
                raise PipelineSdkFailure(
                    error_type="hpc_stage_conflict",
                    message=f"HPC workspace path {workspace_relative_path!r} is already staged with a different sealed digest.",
                    hint="Use a different workspace_path or reuse the artifact already staged at that path.",
                    stage="hpc_stage_validation",
                    retryable=False,
                    sdk_method="hpc.stage_artifact",
                    details={
                        "hpc_workspace_id": hpc_workspace_id,
                        "workspace_relative_path": workspace_relative_path,
                        "existing_artifact_digest": existing_digest,
                        "requested_artifact_digest": artifact_digest,
                    },
                )
            return dict(existing_stage)
        stage_ref_id = (
            "stage_"
            + hashlib.sha256(
                f"{hpc_workspace_id}:{artifact.artifact_id}:{artifact_digest}:{workspace_relative_path}".encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
        )
        payload = {
            "kind": "hpc_stage_ref",
            "stage_ref_id": stage_ref_id,
            "hpc_workspace_id": hpc_workspace_id,
            "artifact_id": artifact.artifact_id,
            "artifact_digest": artifact_digest,
            "workspace_relative_path": workspace_relative_path,
            "source": "artifact_catalog",
            "sandbox_workspace_id": self._pipeline_sandbox_workspace_id(invocation),
        }
        now = utc_now_iso()
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=self._hpc_stage_document_id(
                    hpc_workspace_id, workspace_relative_path
                ),
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="hpc_stage_ref",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )
        return payload

    def _run_pipeline_hpc_fetch_outputs(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        if "register" in params:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_register_parameter_unsupported",
                message="hpc.fetch_outputs does not accept a register parameter in S11 v1.",
                hint="Call ws.fetch_outputs(run); declared outputs are always registered through the artifact boundary.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
            )
        workspace = self._require_hpc_workspace(
            params.get("hpc_workspace"), sdk_method="hpc.fetch_outputs"
        )
        run_id = str(params.get("run_id") or "")
        run = self.repositories.runs.get(run_id)
        if run is None or run.session_id != session.session_id:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message=f"HPC run {run_id!r} is not available in this session.",
                hint="Pass the run handle returned by the approved HPC placement operation.",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={"run_id": run_id},
            )
        pending = self._load_hpc_pending_outputs(
            session_id=session.session_id, run_id=run_id
        )
        if pending is None or str(pending.get("hpc_workspace_id") or "") != str(
            workspace["hpc_workspace_id"]
        ):
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message=f"HPC run {run_id!r} has no declared outputs for this workspace.",
                hint="Fetch only the run handle returned by an approved operation in the same hpc.workspace(...).",
                stage="hpc_fetch_validation",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={
                    "run_id": run_id,
                    "hpc_workspace_id": workspace["hpc_workspace_id"],
                },
            )
        operation_payload = dict(pending)
        controlled_operation_id = str(params.get("controlled_operation_id") or "")
        controlled_operation_digest = str(
            params.get("controlled_operation_digest") or ""
        )
        if controlled_operation_id:
            request_metadata = dict(operation_payload.get("request_metadata") or {})
            existing_operation_id = str(
                request_metadata.get("controlled_operation_id") or ""
            )
            existing_operation_digest = str(
                request_metadata.get("controlled_operation_digest") or ""
            )
            if (
                existing_operation_id
                and existing_operation_id != controlled_operation_id
            ) or (
                existing_operation_digest
                and existing_operation_digest != controlled_operation_digest
            ):
                raise PipelineSdkFailure(
                    error_type="hpc_fetch_controlled_operation_identity_drift",
                    message=(
                        "Pending HPC outputs belong to a different controlled "
                        "operation identity."
                    ),
                    hint="Preserve the pending outputs for operator reconciliation.",
                    stage="hpc_fetch_validation",
                    retryable=False,
                    sdk_method="hpc.fetch_outputs",
                    details={"run_id": run_id},
                )
            request_metadata.update(
                {
                    "controlled_operation_id": controlled_operation_id,
                    "controlled_operation_digest": controlled_operation_digest,
                }
            )
            operation_payload["request_metadata"] = request_metadata
        existing_fetch = self._load_hpc_fetch_result(
            session_id=session.session_id, run_id=run_id
        )
        if existing_fetch is not None:
            return dict(existing_fetch)
        boundary = self._ensure_pipeline_artifact_boundary_workspace(invocation)
        prepared_outputs = [
            (
                output,
                self._prepare_hpc_pending_output_source(
                    invocation=invocation,
                    pending=output,
                    operation_payload=operation_payload,
                ),
            )
            for output in list(pending.get("outputs") or [])
        ]
        registered: list[SessionArtifactRecord] = []
        fetch_refs: list[dict[str, Any]] = []
        for output, source_path in prepared_outputs:
            registered_artifact, fetch_ref = self._register_hpc_pending_output(
                boundary=boundary,
                session_id=session.session_id,
                invocation=invocation,
                run=run,
                hpc_workspace_id=str(workspace["hpc_workspace_id"]),
                pending=output,
                operation_payload=operation_payload,
                source_path=source_path,
            )
            registered.append(registered_artifact)
            fetch_refs.append(fetch_ref)
        payload = {
            "kind": "hpc_fetch_result",
            "hpc_workspace_id": str(workspace["hpc_workspace_id"]),
            "run_id": run_id,
            "status": run.status.value,
            "controlled_operation_id": controlled_operation_id or None,
            "controlled_operation_digest": controlled_operation_digest or None,
            "registered_artifact_ids": [
                artifact.artifact_id for artifact in registered
            ],
            "artifacts": [
                project_artifact_for_agent(artifact) for artifact in registered
            ],
            "fetch_refs": fetch_refs,
        }
        self._save_hpc_fetch_result(
            session_id=session.session_id,
            invocation_id=invocation.invocation_id,
            run_id=run_id,
            payload=payload,
        )
        return payload

    def _sealed_artifact_digest(
        self, artifact: SessionArtifactRecord, *, sdk_method: str
    ) -> str:
        metadata = dict(artifact.metadata or {})
        digest = metadata.get("content_digest") or metadata.get("tree_digest")
        if digest is None or str(digest).strip() == "":
            raise PipelineSdkFailure(
                error_type="hpc_stage_digest_missing",
                message=f"Artifact {artifact.artifact_id!r} does not expose an S08 sealed digest.",
                hint="Register or materialize the input through the artifact boundary before staging it to HPC.",
                stage="hpc_stage_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"artifact_id": artifact.artifact_id},
            )
        return str(digest)

    def _hpc_stage_document_id(
        self, hpc_workspace_id: str, workspace_relative_path: str
    ) -> str:
        digest = hashlib.sha256(
            f"{hpc_workspace_id}:{workspace_relative_path}".encode("utf-8")
        ).hexdigest()[:24]
        return f"hpc_stage_{digest}"

    def _hpc_pending_document_id(self, run_id: str) -> str:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
        return f"hpc_pending_{digest}"

    def _hpc_fetch_document_id(self, run_id: str) -> str:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
        return f"hpc_fetch_{digest}"

    def _find_hpc_stage_ref(
        self,
        *,
        session_id: str,
        hpc_workspace_id: str,
        workspace_relative_path: str,
    ) -> dict[str, Any] | None:
        document = self.repositories.engine_documents.get(
            self._hpc_stage_document_id(hpc_workspace_id, workspace_relative_path)
        )
        if (
            document is None
            or document.session_id != session_id
            or document.document_kind != "hpc_stage_ref"
        ):
            return None
        payload = dict(document.payload)
        if (
            str(payload.get("hpc_workspace_id") or "") == hpc_workspace_id
            and str(payload.get("workspace_relative_path") or "")
            == workspace_relative_path
        ):
            return payload
        return None

    def _load_hpc_pending_outputs(
        self, *, session_id: str, run_id: str
    ) -> dict[str, Any] | None:
        document = self.repositories.engine_documents.get(
            self._hpc_pending_document_id(run_id)
        )
        if (
            document is None
            or document.session_id != session_id
            or document.document_kind != "hpc_pending_outputs"
        ):
            return None
        return dict(document.payload)

    def _load_hpc_fetch_result(
        self, *, session_id: str, run_id: str
    ) -> dict[str, Any] | None:
        document = self.repositories.engine_documents.get(
            self._hpc_fetch_document_id(run_id)
        )
        if (
            document is None
            or document.session_id != session_id
            or document.document_kind != "hpc_fetch_result"
        ):
            return None
        return dict(document.payload)

    def _save_hpc_fetch_result(
        self,
        *,
        session_id: str,
        invocation_id: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=self._hpc_fetch_document_id(run_id),
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="hpc_fetch_result",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )

    def _save_hpc_pending_outputs(
        self,
        *,
        session_id: str,
        invocation: EngineInvocation,
        run: RunRecord,
        operation_key: str,
        sdk_method: str,
        hpc_workspace_id: str,
        stage_refs: list[dict[str, Any]],
        declared_outputs: list[dict[str, Any]],
        request_metadata: dict[str, Any],
        drafts: tuple[BioArtifactDraft, ...] = (),
        execution_artifacts: tuple[ExecutionArtifactRef, ...] = (),
        raw_result: dict[str, Any] | None = None,
        allow_synthetic_missing: bool = False,
    ) -> None:
        validation_stage = (
            "bio_tools_output_validation"
            if sdk_method.startswith("bio_tools.")
            else "hpc_output_validation"
        )
        declared_by_path = {
            self._validate_hpc_workspace_path(
                str(item.get("path") or ""), sdk_method=sdk_method
            ): dict(item)
            for item in declared_outputs
        }
        outputs: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for draft in drafts:
            relative_path = self._validate_hpc_workspace_path(
                draft.relative_path, sdk_method=sdk_method
            )
            if declared_by_path and relative_path not in declared_by_path:
                continue
            seen_paths.add(relative_path)
            outputs.append(
                {
                    "relative_path": relative_path,
                    "declared_output": declared_by_path.get(
                        relative_path, {"path": relative_path}
                    ),
                    "artifact_kind": draft.kind.value,
                    "format": draft.format,
                    "title": draft.title,
                    "content": draft.content,
                    "metadata": dict(draft.metadata),
                }
            )
        for artifact in execution_artifacts:
            relative_path = self._validate_hpc_workspace_path(
                artifact.relative_path, sdk_method=sdk_method
            )
            if declared_by_path and relative_path not in declared_by_path:
                continue
            if not allow_synthetic_missing and not Path(artifact.storage_uri).exists():
                raise PipelineSdkFailure(
                    error_type="declared_output_missing",
                    message=f"{sdk_method} runner artifact {relative_path!r} was not fetched to a readable local path.",
                    hint="Inspect runner fetch logs; do not synthesize missing declared outputs.",
                    stage=validation_stage,
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"missing_outputs": [relative_path]},
                )
            seen_paths.add(relative_path)
            declared = declared_by_path.get(relative_path, {"path": relative_path})
            artifact_metadata = dict(getattr(artifact, "metadata", None) or {})
            outputs.append(
                {
                    "relative_path": relative_path,
                    "declared_output": declared,
                    "artifact_kind": artifact.kind.value,
                    "format": declared.get("format") or artifact_metadata.get("format"),
                    "title": PurePosixPath(relative_path).name,
                    "source_uri": artifact.storage_uri,
                    "metadata": artifact_metadata,
                }
            )
        missing_declared = [
            (relative_path, declared)
            for relative_path, declared in declared_by_path.items()
            if relative_path not in seen_paths
        ]
        if missing_declared and not allow_synthetic_missing:
            raise PipelineSdkFailure(
                error_type="declared_output_missing",
                message=f"{sdk_method} did not produce all declared outputs.",
                hint="Inspect runner logs and command templates; do not synthesize missing declared outputs.",
                stage=validation_stage,
                retryable=False,
                sdk_method=sdk_method,
                details={
                    "missing_outputs": [
                        relative_path for relative_path, _ in missing_declared
                    ]
                },
            )
        for relative_path, declared in missing_declared:
            outputs.append(
                {
                    "relative_path": relative_path,
                    "declared_output": declared,
                    "artifact_kind": self._artifact_kind_from_declared(
                        declared,
                        relative_path,
                        sdk_method=sdk_method,
                    ).value,
                    "format": declared.get("format"),
                    "title": PurePosixPath(relative_path).name,
                    "metadata": {},
                    "synthetic_source": True,
                }
            )
        payload = {
            "kind": "hpc_pending_outputs",
            "run_id": run.run_id,
            "runner_run_id": run.runner_run_id,
            "operation_key": operation_key,
            "sdk_method": sdk_method,
            "hpc_workspace_id": hpc_workspace_id,
            "stage_refs": stage_refs,
            "declared_outputs": declared_outputs,
            "selected_backend": "hpc",
            "status": run.status.value,
            "cutover_eligible": not any(
                bool(item.get("synthetic_source")) for item in outputs
            ),
            "raw_result": dict(raw_result or {}),
            "request_metadata": dict(request_metadata),
            "outputs": outputs,
        }
        now = utc_now_iso()
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=self._hpc_pending_document_id(run.run_id),
                session_id=session_id,
                invocation_id=invocation.invocation_id,
                document_kind="hpc_pending_outputs",
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )

    def _ensure_pipeline_artifact_boundary_workspace(
        self,
        invocation: EngineInvocation,
    ) -> ArtifactBoundaryService:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        runtime_identity = dict(pipeline.get("sandbox_runtime_identity") or {})
        required_identity_fields = _SANDBOX_IDENTITY_FIELDS
        missing_identity_fields = sorted(
            required_identity_fields - set(runtime_identity)
        )
        if missing_identity_fields:
            raise PipelineSdkFailure(
                error_type="sandbox_runtime_identity_unavailable",
                message="Pipeline artifact registration requires the approved sandbox runtime identity.",
                hint="Recreate the execution plan with an immutable image and Pipeline SDK identity.",
                stage="artifact_registration",
                retryable=False,
                details={"missing_fields": missing_identity_fields},
            )
        sandbox_workspace_id = self._pipeline_sandbox_workspace_id(invocation)
        workspace_root = (
            self.sandbox_workspace_root
            or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
        )
        workspace_path = workspace_root / sandbox_workspace_id
        workspace = self.repositories.sandbox_workspaces.get(sandbox_workspace_id)
        try:
            _ensure_pipeline_workspace_layout(
                workspace_path,
                create=workspace is None,
            )
        except OSError as exc:
            raise PipelineSdkFailure(
                error_type="sandbox_volume_corrupt",
                message="Pipeline sandbox workspace layout is incomplete or invalid.",
                hint="Ask the Host operator to inspect or repair the workspace volume before retrying.",
                stage="artifact_registration",
                retryable=False,
            ) from exc
        if workspace is not None:
            workspace_identity = {
                "configured_image_ref": workspace.image_ref,
                "image_digest": workspace.image_digest,
                "sandbox_protocol_version": workspace.sandbox_protocol_version,
            }
            approved_workspace_identity = {
                key: str(runtime_identity[key]) for key in workspace_identity
            }
            if workspace_identity != approved_workspace_identity:
                raise PipelineSdkFailure(
                    error_type="sandbox_runtime_identity_drift",
                    message="Sandbox workspace image identity differs from the approved runtime identity.",
                    hint="Create a new execution plan or sandbox run after refreshing the workspace image.",
                    stage="artifact_registration",
                    retryable=False,
                    details={
                        "workspace_identity": workspace_identity,
                        "approved_workspace_identity": approved_workspace_identity,
                    },
                )
        if workspace is None:
            now = utc_now_iso()
            member_id = f"member_{hashlib.sha256(sandbox_workspace_id.encode('utf-8')).hexdigest()[:16]}"
            agent_id = f"agent:pipeline:{_safe_ref(invocation.invocation_id)}"
            self.repositories.agents.save(
                AgentMember(
                    agent_id=agent_id,
                    session_id=invocation.session_id,
                    lane_id=invocation.lane_id,
                    task_id=invocation.task_id,
                    name="Pipeline executor",
                    role="executor",
                    status=AgentMemberStatus.IDLE,
                    parent_agent_id=None,
                    created_at=now,
                    updated_at=now,
                    idle_since=now,
                    member_id=member_id,
                )
            )
            workspace = SandboxWorkspaceRecord(
                sandbox_workspace_id=sandbox_workspace_id,
                session_id=invocation.session_id,
                agent_member_id=member_id,
                agent_id=agent_id,
                focus_task_id=invocation.task_id,
                focus_lane_id=invocation.lane_id,
                status=SandboxWorkspaceStatus.READY,
                image_ref=str(runtime_identity["configured_image_ref"]),
                image_digest=str(runtime_identity["image_digest"]),
                image_version=str(runtime_identity["runtime_identity_digest"]),
                sandbox_protocol_version=str(
                    runtime_identity["sandbox_protocol_version"]
                ),
                image_compatibility=SandboxImageCompatibility.COMPATIBLE,
                manifest_version="s11.workspace_manifest.v1",
                volume_digest="",
                quota_summary={},
                directory_summary={},
                materialized_input_artifact_ids=(),
                registered_artifact_ids=(),
                source_code_artifact_ids=(),
                created_at=now,
                last_attached_at=now,
            )
            self.repositories.sandbox_workspaces.save(workspace)
        boundary = ArtifactBoundaryService(
            self.repositories,
            workspace_root=workspace_root,
            blob_store_root=self.artifact_blob_root,
        )
        workspace = (
            self.repositories.sandbox_workspaces.get(sandbox_workspace_id) or workspace
        )
        if not workspace.source_code_artifact_ids:
            source = self._reload_pipeline_source(invocation, pipeline)
            (workspace_path / "src" / "pipeline.py").write_text(
                source.code, encoding="utf-8"
            )
            try:
                boundary.snapshot_code(
                    session_id=invocation.session_id,
                    sandbox_workspace_id=sandbox_workspace_id,
                    paths=["pipeline.py"],
                    entrypoint="pipeline.py",
                    metadata=source.metadata(),
                )
            except ArtifactBoundaryError as exc:
                raise PipelineSdkFailure(
                    error_type=exc.error_code,
                    message=str(exc),
                    hint=exc.hint
                    or "Ensure the executor sandbox source tree is snapshotted before registering outputs.",
                    stage="hpc_fetch_register",
                    retryable=False,
                    sdk_method="hpc.fetch_outputs",
                    details=exc.details,
                ) from exc
        return boundary

    def _register_hpc_pending_output(
        self,
        *,
        boundary: ArtifactBoundaryService,
        session_id: str,
        invocation: EngineInvocation,
        run: RunRecord,
        hpc_workspace_id: str,
        pending: dict[str, Any],
        operation_payload: dict[str, Any],
        source_path: Path,
    ) -> tuple[SessionArtifactRecord, dict[str, Any]]:
        relative_path = self._validate_hpc_workspace_path(
            str(pending.get("relative_path") or ""),
            sdk_method="hpc.fetch_outputs",
        )
        sandbox_workspace_id = self._pipeline_sandbox_workspace_id(invocation)
        output_digest = self._digest_hpc_output_source(source_path)
        fetch_ref_id = (
            "fetch_"
            + hashlib.sha256(
                f"{hpc_workspace_id}:{run.run_id}:{relative_path}:{output_digest}".encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
        )
        declared = dict(pending.get("declared_output") or {"path": relative_path})
        metadata = {
            **dict(pending.get("metadata") or {}),
            "hpc_workspace_id": hpc_workspace_id,
            "fetch_ref_id": fetch_ref_id,
            "declared_output_path": relative_path,
            "declared_output": declared,
            "declared_outputs": list(operation_payload.get("declared_outputs") or []),
            "stage_refs": list(operation_payload.get("stage_refs") or []),
            "selected_backend": "hpc",
            "sdk_method": operation_payload.get("sdk_method"),
            "pipeline_step_id": operation_payload.get("operation_key"),
            "runner_run_id": run.runner_run_id,
            "pipeline_invocation_id": invocation.invocation_id,
            "planned_fetch_intent": True,
            "synthetic_source": bool(pending.get("synthetic_source")),
            "cutover_eligible": not bool(pending.get("synthetic_source")),
            **dict(operation_payload.get("request_metadata") or {}),
        }
        if operation_payload.get(
            "sdk_method"
        ) == "bio_tools.cdhit" and relative_path.endswith("/clusters.csv"):
            metadata.update(
                {
                    "membership_schema_id": CDHIT_MEMBERSHIP_SCHEMA_ID,
                    "membership_columns": list(CDHIT_MEMBERSHIP_COLUMNS),
                    "row_semantics": "one_member_per_row",
                }
            )
        if pending.get("synthetic_source"):
            metadata.update(
                {
                    "provider_status": "fixture_non_cutover",
                    "tool_status": "fixture_non_cutover",
                    "scientific_status": "fixture_non_cutover",
                }
            )
        format_value = pending.get("format") or declared.get("format")
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        source_snapshot_artifact_id = None
        if pipeline.get("adapter_operation_id"):
            source_snapshot_artifact_id = str(
                pipeline.get("source_code_artifact_id") or ""
            )
        try:
            result = boundary.register(
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                path=f"/workspace/output/{relative_path}",
                kind=self._artifact_kind_from_declared(
                    declared,
                    relative_path,
                    sdk_method=str(
                        operation_payload.get("sdk_method") or "hpc.fetch_outputs"
                    ),
                ),
                format=None if format_value in {None, ""} else str(format_value),
                metadata=metadata,
                invocation_id=invocation.invocation_id,
                run_id=run.run_id,
                source_snapshot_artifact_id=source_snapshot_artifact_id,
            )
        except ArtifactBoundaryError as exc:
            raise PipelineSdkFailure(
                error_type=exc.error_code,
                message=str(exc),
                hint=exc.hint
                or "Declared output registration through the S08 artifact boundary failed.",
                stage="hpc_fetch_register",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details=exc.details,
            ) from exc
        artifact_digest = result.content_digest or result.tree_digest or output_digest
        fetch_ref = {
            "fetch_ref_id": fetch_ref_id,
            "hpc_workspace_id": hpc_workspace_id,
            "run_id": run.run_id,
            "declared_output_path": relative_path,
            "registered_artifact_id": result.artifact.artifact_id,
            "output_digest": artifact_digest,
        }
        return result.artifact, fetch_ref

    def _prepare_hpc_pending_output_source(
        self,
        *,
        invocation: EngineInvocation,
        pending: dict[str, Any],
        operation_payload: dict[str, Any],
    ) -> Path:
        relative_path = self._validate_hpc_workspace_path(
            str(pending.get("relative_path") or ""),
            sdk_method="hpc.fetch_outputs",
        )
        sandbox_workspace_id = self._pipeline_sandbox_workspace_id(invocation)
        workspace_root = (
            self.sandbox_workspace_root
            or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
        )
        source_path = workspace_root / sandbox_workspace_id / "output" / relative_path
        self._write_hpc_pending_output_source(source_path, pending)
        self._validate_hpc_pending_output_source(
            source_path,
            sdk_method=str(operation_payload.get("sdk_method") or "hpc.fetch_outputs"),
            relative_path=relative_path,
            declared=dict(pending.get("declared_output") or {}),
            operation_payload=operation_payload,
        )
        return source_path

    def _write_hpc_pending_output_source(
        self, target: Path, pending: dict[str, Any]
    ) -> None:
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        source_uri = pending.get("source_uri")
        if isinstance(source_uri, str) and source_uri and Path(source_uri).exists():
            source = Path(source_uri)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copyfile(source, target)
            return
        content = pending.get("content")
        if not pending.get("synthetic_source") and not isinstance(content, str):
            raise PipelineSdkFailure(
                error_type="declared_output_missing",
                message="HPC output has no readable source or fetched content.",
                hint="Inspect runner fetch results; synthetic output is allowed only in explicit non-cutover fixtures.",
                stage="hpc_fetch_register",
                retryable=False,
                sdk_method="hpc.fetch_outputs",
                details={"relative_path": pending.get("relative_path")},
            )
        if self._pending_output_is_directory(pending):
            target.mkdir(parents=True, exist_ok=True)
            (target / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "s11_controlled_fetch",
                        "path": pending.get("relative_path"),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return
        if not isinstance(content, str):
            content = self._dummy_content_for_declared_output(pending)
        target.write_text(content, encoding="utf-8")

    def _validate_hpc_pending_output_source(
        self,
        path: Path,
        *,
        sdk_method: str,
        relative_path: str,
        declared: dict[str, Any],
        operation_payload: dict[str, Any] | None = None,
    ) -> None:
        if not sdk_method.startswith("bio_tools."):
            return
        if not path.exists():
            raise PipelineSdkFailure(
                error_type="declared_output_missing",
                message=f"{sdk_method} declared output {relative_path!r} was not fetched.",
                hint="Inspect runner fetch logs and command template output paths.",
                stage="bio_tools_output_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"missing_outputs": [relative_path]},
            )
        if path.is_dir():
            raise PipelineSdkFailure(
                error_type="output_validation_failed",
                message=f"{sdk_method} declared output {relative_path!r} must be a file.",
                hint="Declare file outputs for S14 bio_tools routes.",
                stage="bio_tools_output_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"path": relative_path},
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        format_value = str(declared.get("format") or "").lower()
        if relative_path.endswith(".hmm") or format_value == "hmm":
            valid = content.startswith("HMMER")
        elif sdk_method == "bio_tools.cdhit" and (
            relative_path.endswith("/clusters.csv") or format_value == "csv"
        ):
            self._validate_cdhit_membership_output(
                path,
                relative_path=relative_path,
                operation_payload=operation_payload,
            )
            return
        elif relative_path.endswith(".csv") or format_value == "csv":
            lines = [line for line in content.splitlines() if line.strip()]
            header = set(lines[0].split(",")) if lines else set()
            valid = bool(lines) and {"target", "accession", "evalue", "score"}.issubset(
                header
            )
        elif relative_path.endswith(
            (".fasta", ".fa", ".faa", ".afa")
        ) or format_value in {"fasta", "fa", "faa", "afa"}:
            records = sum(1 for line in content.splitlines() if line.startswith(">"))
            valid = records >= (
                2 if sdk_method in {"bio_tools.mafft", "bio_tools.hmmalign"} else 1
            )
        else:
            valid = bool(content.strip())
        if not valid:
            raise PipelineSdkFailure(
                error_type="output_validation_failed",
                message=f"{sdk_method} declared output {relative_path!r} failed minimal format validation.",
                hint="Check the S14 command template and normalize runner raw outputs before registering artifacts.",
                stage="bio_tools_output_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"path": relative_path, "format": format_value or None},
            )

    def _validate_cdhit_membership_output(
        self,
        path: Path,
        *,
        relative_path: str,
        operation_payload: dict[str, Any] | None,
    ) -> None:
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, strict=True)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
        except (OSError, csv.Error) as exc:
            raise self._cdhit_membership_failure(
                relative_path=relative_path,
                reason="invalid_csv",
                details={"error": type(exc).__name__},
            ) from exc
        if fieldnames != list(CDHIT_MEMBERSHIP_COLUMNS):
            raise self._cdhit_membership_failure(
                relative_path=relative_path,
                reason="schema_mismatch",
                details={
                    "schema_id": CDHIT_MEMBERSHIP_SCHEMA_ID,
                    "expected_columns": list(CDHIT_MEMBERSHIP_COLUMNS),
                    "actual_columns": fieldnames,
                },
            )
        if not rows:
            raise self._cdhit_membership_failure(
                relative_path=relative_path,
                reason="membership_empty",
            )

        member_rows: dict[str, dict[str, str]] = {}
        clusters: dict[str, list[dict[str, str]]] = {}
        for row_index, raw_row in enumerate(rows, start=2):
            if None in raw_row or any(value is None for value in raw_row.values()):
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="row_shape_mismatch",
                    details={"row": row_index},
                )
            row = {column: str(raw_row[column]) for column in CDHIT_MEMBERSHIP_COLUMNS}
            empty_columns = [
                column for column, value in row.items() if not value.strip()
            ]
            if empty_columns:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="missing_membership_value",
                    details={"row": row_index, "columns": empty_columns},
                )
            member_id = row["member_id"]
            if member_id in member_rows:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="duplicate_membership",
                    details={"row": row_index, "member_id": member_id},
                )
            if row["is_representative"] not in {"true", "false"}:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="invalid_representative_flag",
                    details={"row": row_index, "value": row["is_representative"]},
                )
            identity_text = row["identity_to_representative"]
            if re.fullmatch(r"(?:0|1)\.[0-9]{6}", identity_text) is None:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="invalid_identity",
                    details={"row": row_index, "value": identity_text},
                )
            try:
                identity = Decimal(identity_text)
            except InvalidOperation as exc:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="invalid_identity",
                    details={"row": row_index, "value": identity_text},
                ) from exc
            if not identity.is_finite() or identity < 0 or identity > 1:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="invalid_identity",
                    details={"row": row_index, "value": identity_text},
                )
            if re.fullmatch(r"[1-9][0-9]*", row["member_length"]) is None:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="invalid_member_length",
                    details={"row": row_index, "value": row["member_length"]},
                )
            member_rows[member_id] = row
            clusters.setdefault(row["cluster_id"], []).append(row)

        for cluster_id, cluster_rows in clusters.items():
            representative_rows = [
                row for row in cluster_rows if row["is_representative"] == "true"
            ]
            if len(representative_rows) != 1:
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="representative_membership_missing_or_duplicate",
                    details={
                        "cluster_id": cluster_id,
                        "representative_count": len(representative_rows),
                    },
                )
            representative_row = representative_rows[0]
            representative_id = representative_row["member_id"]
            if (
                representative_row["representative_id"] != representative_id
                or representative_row["identity_to_representative"] != "1.000000"
                or any(
                    row["representative_id"] != representative_id
                    for row in cluster_rows
                )
            ):
                raise self._cdhit_membership_failure(
                    relative_path=relative_path,
                    reason="inconsistent_representative_membership",
                    details={
                        "cluster_id": cluster_id,
                        "representative_id": representative_id,
                    },
                )

        expected_members = self._expected_cdhit_members(operation_payload)
        if expected_members is None:
            return
        actual_member_ids = set(member_rows)
        expected_member_ids = set(expected_members)
        missing_member_ids = sorted(expected_member_ids - actual_member_ids)
        unexpected_member_ids = sorted(actual_member_ids - expected_member_ids)
        length_mismatches = {
            member_id: {
                "expected": expected_members[member_id],
                "actual": int(member_rows[member_id]["member_length"]),
            }
            for member_id in sorted(expected_member_ids & actual_member_ids)
            if int(member_rows[member_id]["member_length"])
            != expected_members[member_id]
        }
        if missing_member_ids or unexpected_member_ids or length_mismatches:
            raise self._cdhit_membership_failure(
                relative_path=relative_path,
                reason="membership_input_mismatch",
                details={
                    "missing_member_ids": missing_member_ids,
                    "unexpected_member_ids": unexpected_member_ids,
                    "length_mismatches": length_mismatches,
                },
            )

    def _expected_cdhit_members(
        self,
        operation_payload: dict[str, Any] | None,
    ) -> dict[str, int] | None:
        if operation_payload is None:
            return None
        stage_refs = list(operation_payload.get("stage_refs") or [])
        if len(stage_refs) != 1 or not isinstance(stage_refs[0], dict):
            raise self._cdhit_membership_failure(
                relative_path="bio_tools/cdhit/clusters.csv",
                reason="membership_input_unavailable",
                details={"stage_ref_count": len(stage_refs)},
            )
        artifact_id = str(stage_refs[0].get("artifact_id") or "")
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None:
            raise self._cdhit_membership_failure(
                relative_path="bio_tools/cdhit/clusters.csv",
                reason="membership_input_unavailable",
                details={"artifact_id": artifact_id},
            )
        try:
            content = Path(artifact.storage_uri).read_text(encoding="utf-8")
        except OSError as exc:
            raise self._cdhit_membership_failure(
                relative_path="bio_tools/cdhit/clusters.csv",
                reason="membership_input_unavailable",
                details={"artifact_id": artifact_id},
            ) from exc
        members: dict[str, int] = {}
        current_id: str | None = None
        current_length = 0
        for line in content.splitlines():
            if line.startswith(">"):
                if current_id is not None:
                    members[current_id] = current_length
                header = line[1:].strip()
                current_id = header.split(maxsplit=1)[0] if header else ""
                if not current_id or current_id in members:
                    raise self._cdhit_membership_failure(
                        relative_path="bio_tools/cdhit/clusters.csv",
                        reason="duplicate_or_empty_input_member_id",
                        details={"artifact_id": artifact_id, "member_id": current_id},
                    )
                current_length = 0
            elif line.strip() and current_id is not None:
                current_length += len(line.strip())
        if current_id is not None:
            if current_id in members:
                raise self._cdhit_membership_failure(
                    relative_path="bio_tools/cdhit/clusters.csv",
                    reason="duplicate_or_empty_input_member_id",
                    details={"artifact_id": artifact_id, "member_id": current_id},
                )
            members[current_id] = current_length
        if not members or any(length <= 0 for length in members.values()):
            raise self._cdhit_membership_failure(
                relative_path="bio_tools/cdhit/clusters.csv",
                reason="membership_input_unavailable",
                details={"artifact_id": artifact_id},
            )
        return members

    def _cdhit_membership_failure(
        self,
        *,
        relative_path: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type="output_validation_failed",
            message=(
                f"bio_tools.cdhit declared membership output {relative_path!r} "
                f"does not satisfy {CDHIT_MEMBERSHIP_SCHEMA_ID}."
            ),
            hint="Regenerate clusters.csv from the complete CD-HIT .clstr output; do not infer or aggregate memberships.",
            stage="bio_tools_output_validation",
            retryable=False,
            sdk_method="bio_tools.cdhit",
            details={
                "path": relative_path,
                "schema_id": CDHIT_MEMBERSHIP_SCHEMA_ID,
                "reason": reason,
                **(details or {}),
            },
        )

    def _pending_output_is_directory(self, pending: dict[str, Any]) -> bool:
        declared = dict(pending.get("declared_output") or {})
        kind = str(declared.get("kind") or pending.get("artifact_kind") or "").lower()
        format_value = str(
            declared.get("format") or pending.get("format") or ""
        ).lower()
        return kind == "directory" or format_value == "fpocket"

    def _dummy_content_for_declared_output(self, pending: dict[str, Any]) -> str:
        declared = dict(pending.get("declared_output") or {})
        format_value = str(
            declared.get("format") or pending.get("format") or ""
        ).lower()
        path = str(pending.get("relative_path") or "output")
        if format_value in {"fa", "faa", "fasta"}:
            return ">s11_fetch_placeholder\nMKTAYIAKQRQISFVKSHFSRQ\n"
        if format_value == "hmm":
            return "HMMER3/f [fixture]\nNAME s11_fetch_placeholder\n//\n"
        if format_value == "csv":
            return "target,accession,evalue,score\n"
        if format_value == "json":
            return "{}\n"
        if format_value in {"pdb", "pdbqt"}:
            return "REMARK S11 controlled fetch placeholder\n"
        return f"S11 controlled fetch placeholder for {path}\n"

    def _artifact_kind_from_declared(
        self,
        declared: dict[str, Any],
        relative_path: str,
        *,
        sdk_method: str,
    ) -> ArtifactKind:
        value = declared.get("kind")
        if value is not None:
            if str(value).lower() == "directory":
                # ``directory`` is the established expected-output shape
                # sentinel. Catalog registration still uses a real
                # ArtifactKind inferred from the fixed relative path.
                return _artifact_kind_from_path(relative_path)
            try:
                return ArtifactKind(str(value))
            except ValueError as exc:
                allowed_values = [item.value for item in ArtifactKind]
                raise PipelineSdkFailure(
                    error_type="artifact_kind_invalid",
                    message=f"artifact kind {value!r} is invalid",
                    hint=f"Use exactly one of: {', '.join(allowed_values)}.",
                    stage="hpc_output_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "allowed_values": allowed_values,
                        "declared_kind": str(value),
                        "path": relative_path,
                    },
                ) from exc
        return _artifact_kind_from_path(relative_path)

    def _digest_hpc_output_source(self, path: Path) -> str:
        if path.is_file():
            return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        files: list[dict[str, Any]] = []
        for child in sorted(
            path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()
        ):
            if child.is_dir():
                continue
            content = child.read_bytes()
            files.append(
                {
                    "relative_path": child.relative_to(path).as_posix(),
                    "content_digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                    "size_bytes": len(content),
                }
            )
        payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    def _require_stage_ref_artifact_id(
        self,
        ref: Any,
        *,
        placement: dict[str, Any],
        slot_name: str,
        sdk_method: str,
        session_id: str | None = None,
    ) -> str:
        if (
            not isinstance(ref, dict)
            or not ref.get("stage_ref_id")
            or not ref.get("artifact_id")
        ):
            raise PipelineSdkFailure(
                error_type="hpc_stage_ref_required",
                message=f"{sdk_method} requires {slot_name} to be a staged artifact ref.",
                hint="Call ws.stage_artifact(artifact_id, workspace_path=...) and pass the returned ref.",
                stage="hpc_stage_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        if str(ref.get("hpc_workspace_id") or "") != str(
            placement.get("hpc_workspace_id") or ""
        ):
            raise PipelineSdkFailure(
                error_type="hpc_workspace_forbidden",
                message=f"{sdk_method} {slot_name} was staged into a different HPC workspace.",
                hint="Stage all inputs into the same hpc.workspace(...) passed as placement.",
                stage="hpc_stage_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"slot_name": slot_name},
            )
        if session_id is not None:
            artifact_id = str(ref["artifact_id"])
            artifact = self.repositories.artifacts.get(artifact_id)
            if artifact is None or artifact.session_id != session_id:
                raise PipelineSdkFailure(
                    error_type="artifact_not_available",
                    message=f"Artifact {artifact_id!r} is not available in this session.",
                    hint="Stage only catalog artifacts from the current session.",
                    stage="hpc_stage_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"artifact_id": artifact_id, "slot_name": slot_name},
                )
            expected_digest = self._sealed_artifact_digest(
                artifact, sdk_method=sdk_method
            )
            actual_digest = str(ref.get("artifact_digest") or "")
            if actual_digest != expected_digest:
                raise PipelineSdkFailure(
                    error_type="artifact_digest_mismatch",
                    message=f"{sdk_method} {slot_name} staged digest does not match the catalog sealed digest.",
                    hint="Use the StageRef returned by ws.stage_artifact for the current artifact version.",
                    stage="hpc_stage_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "artifact_id": artifact_id,
                        "slot_name": slot_name,
                        "expected_digest": expected_digest,
                        "actual_digest": actual_digest,
                    },
                )
            workspace_path = str(ref.get("workspace_relative_path") or "")
            if workspace_path:
                self._validate_hpc_workspace_path(workspace_path, sdk_method=sdk_method)
        return str(ref["artifact_id"])

    def _require_declared_outputs(
        self, params: dict[str, Any], *, sdk_method: str
    ) -> list[dict[str, Any]]:
        expected_outputs = [
            dict(item)
            for item in list(params.get("expected_outputs") or [])
            if isinstance(item, dict)
        ]
        if not expected_outputs:
            raise PipelineSdkFailure(
                error_type="hpc_fetch_not_declared",
                message=f"{sdk_method} requires declared expected_outputs.",
                hint="Declare the workspace-relative output paths that ws.fetch_outputs may register.",
                stage="hpc_output_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        for output in expected_outputs:
            self._validate_hpc_workspace_path(
                str(output.get("path") or ""), sdk_method=sdk_method
            )
        return expected_outputs

    def _require_canonical_bio_tool_outputs(
        self,
        method: str,
        declared_outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        expected_paths = sorted(
            str(item["path"])
            for item in self._planned_bio_tool_expected_outputs(method)
        )
        declared_paths = sorted(
            str(item.get("path") or "") for item in declared_outputs
        )
        if declared_paths != expected_paths:
            raise PipelineSdkFailure(
                error_type="bio_tool_output_contract_mismatch",
                message=(
                    f"{method} expected_outputs do not match its fixed runner template."
                ),
                hint=(
                    "Declare exactly these workspace-relative output paths: "
                    + ", ".join(expected_paths)
                ),
                stage="hpc_output_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "declared_paths": declared_paths,
                    "expected_paths": expected_paths,
                },
            )
        expected_by_path = {
            str(item["path"]): dict(item)
            for item in self._planned_bio_tool_expected_outputs(method)
        }
        mismatches: list[dict[str, str]] = []
        for declared in declared_outputs:
            path = str(declared.get("path") or "")
            expected = expected_by_path[path]
            if declared.get("kind") is not None:
                raw_kind = str(declared.get("kind"))
                declared_kind = (
                    raw_kind
                    if raw_kind.lower() == "directory"
                    else self._artifact_kind_from_declared(
                        declared,
                        path,
                        sdk_method=method,
                    ).value
                )
                if declared_kind != str(expected["kind"]):
                    mismatches.append(
                        {
                            "field": "kind",
                            "path": path,
                            "declared": declared_kind,
                            "expected": str(expected["kind"]),
                        }
                    )
            if declared.get("format") is not None:
                declared_format = str(declared.get("format") or "")
                expected_format = str(expected["format"])
                if declared_format != expected_format:
                    mismatches.append(
                        {
                            "field": "format",
                            "path": path,
                            "declared": declared_format,
                            "expected": expected_format,
                        }
                    )
        if mismatches:
            raise PipelineSdkFailure(
                error_type="bio_tool_output_contract_mismatch",
                message=(
                    f"{method} expected_outputs kind/format do not match its fixed runner template."
                ),
                hint="Omit inferred fields or declare the exact canonical kind/format pair.",
                stage="hpc_output_validation",
                retryable=False,
                sdk_method=method,
                details={"mismatches": mismatches},
            )
        return [
            {
                **dict(declared),
                "kind": str(expected_by_path[str(declared["path"])]["kind"]),
                "format": str(expected_by_path[str(declared["path"])]["format"]),
            }
            for declared in declared_outputs
        ]

    def _require_bio_route_policy(self, method: str) -> dict[str, Any]:
        route_policy_id = BIO_PROVIDER_ROUTE_POLICY_IDS.get(method)
        policy = dict(S12_ROUTE_POLICIES.get(str(route_policy_id)) or {})
        if not route_policy_id or not policy:
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} has no S13 provider route policy.",
                hint="Register a provider_http route policy before executing this SDK operation.",
                stage="provider_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"method": method},
            )
        if (
            policy.get("status") != "ok"
            or policy.get("selected_backend") != "provider_http"
        ):
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} provider route policy is not executable.",
                hint="Fix the route policy evidence/backend linkage before executing provider requests.",
                stage="provider_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy_id,
                    "policy": _sanitize_provider_value(policy),
                },
            )
        provider_config_digest = str(policy.get("provider_config_digest") or "")
        if not provider_config_digest:
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} route policy does not declare a provider config digest.",
                hint="Add provider_config_digest to the route policy before executing provider requests.",
                stage="provider_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"route_policy_id": route_policy_id},
            )
        return {"route_policy_id": route_policy_id, **policy}

    def _require_bio_tool_route_policy(self, method: str) -> dict[str, Any]:
        route_policy_id = BIO_TOOL_ROUTE_POLICY_IDS.get(method)
        policy = dict(S12_ROUTE_POLICIES.get(str(route_policy_id)) or {})
        if not route_policy_id or not policy:
            raise PipelineSdkFailure(
                error_type="toolchain_not_configured",
                message=f"{method} has no S14 bio tools route policy.",
                hint="Register a versioned bio_tools route policy before executing this SDK operation.",
                stage="bio_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"method": method},
            )
        if (
            policy.get("status") == "disabled"
            or policy.get("error_code") == "unsupported_in_s14"
        ):
            raise PipelineSdkFailure(
                error_type="unsupported_in_s14",
                message=(
                    "bio_tools.hmmer_search_cli is disabled in Session 14; "
                    "use bio.hmmer_search(..., database='refprot') for the AOX/HMM main route."
                ),
                hint="Do not retry through Host-local HMMER, fixture, or a sibling backend.",
                stage="bio_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy_id,
                    "route_reason": policy.get("route_reason"),
                },
            )
        if policy.get("status") != "ok" or policy.get("selected_backend") != "hpc":
            raise PipelineSdkFailure(
                error_type=str(
                    policy.get("error_code") or "route_prerequisite_missing"
                ),
                message=f"{method} HPC route policy is not executable.",
                hint="Fix the route policy evidence, runtime packaging, and toolchain linkage before running the tool.",
                stage="bio_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy_id,
                    "policy": _sanitize_provider_value(policy),
                },
            )
        if not policy.get("runtime_packaging_id") or not policy.get("toolchain_id"):
            raise PipelineSdkFailure(
                error_type="toolchain_not_configured",
                message=f"{method} route policy does not declare runtime packaging and toolchain ids.",
                hint="Add runtime_packaging_id and toolchain_id to the route policy before executing the tool.",
                stage="bio_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"route_policy_id": route_policy_id},
            )
        return {"route_policy_id": route_policy_id, **policy}

    def _require_structure_tool_route_policy(self, method: str) -> dict[str, Any]:
        route_policy_id = STRUCTURE_TOOL_ROUTE_POLICY_IDS.get(method)
        policy = dict(S12_ROUTE_POLICIES.get(str(route_policy_id)) or {})
        if not route_policy_id or not policy:
            raise PipelineSdkFailure(
                error_type="toolchain_not_configured",
                message=f"{method} has no structure_tools HPC route policy.",
                hint="Register a versioned structure_tools route policy before executing this SDK operation.",
                stage="structure_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"method": method},
            )
        if policy.get("status") != "ok" or policy.get("selected_backend") != "hpc":
            raise PipelineSdkFailure(
                error_type=str(
                    policy.get("error_code") or "route_prerequisite_missing"
                ),
                message=f"{method} HPC route policy is not executable.",
                hint="Fix the route policy evidence, runtime packaging, and toolchain linkage before running the tool.",
                stage="structure_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy_id,
                    "policy": _sanitize_provider_value(policy),
                },
            )
        if not policy.get("runtime_packaging_id") or not policy.get("toolchain_id"):
            raise PipelineSdkFailure(
                error_type="toolchain_not_configured",
                message=f"{method} route policy does not declare runtime packaging and toolchain ids.",
                hint="Add runtime_packaging_id and toolchain_id to the route policy before executing the tool.",
                stage="structure_tools_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"route_policy_id": route_policy_id},
            )
        return {"route_policy_id": route_policy_id, **policy}

    def _validate_bio_tool_fasta_artifact(
        self,
        artifact: SessionArtifactRecord,
        *,
        sdk_method: str,
        min_records: int = 1,
    ) -> None:
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        suffix_ok = artifact.relative_path.lower().endswith(
            (".fasta", ".fa", ".faa", ".afa")
        )
        if metadata_format not in {"fasta", "fa", "faa", "afa"} and not suffix_ok:
            raise PipelineSdkFailure(
                error_type="invalid_fasta",
                message=f"Artifact {artifact.artifact_id!r} must be a FASTA sequence artifact.",
                hint="Provide a FASTA artifact generated by bio.* or bio_tools.*.",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={
                    "artifact_id": artifact.artifact_id,
                    "format": metadata_format,
                },
            )
        try:
            content = Path(artifact.storage_uri).read_text(encoding="utf-8")
        except OSError as exc:
            raise PipelineSdkFailure(
                error_type="artifact_not_available",
                message=f"Artifact {artifact.artifact_id!r} could not be read for bio tool validation.",
                hint="Use a visible artifact with stable sealed content.",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"artifact_id": artifact.artifact_id},
            ) from exc
        record_count = sum(1 for line in content.splitlines() if line.startswith(">"))
        if record_count < min_records:
            raise PipelineSdkFailure(
                error_type="invalid_fasta",
                message=f"Artifact {artifact.artifact_id!r} is empty or not valid FASTA.",
                hint=f"Provide a FASTA with at least {min_records} sequence record(s).",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={
                    "artifact_id": artifact.artifact_id,
                    "record_count": record_count,
                },
            )

    def _validate_bio_tool_alignment_artifact(
        self, artifact: SessionArtifactRecord, *, sdk_method: str
    ) -> None:
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if metadata_format in {
            "sto",
            "stockholm",
        } or artifact.relative_path.lower().endswith((".sto", ".stockholm")):
            try:
                content = Path(artifact.storage_uri).read_text(encoding="utf-8")
            except OSError as exc:
                raise PipelineSdkFailure(
                    error_type="artifact_not_available",
                    message=f"Alignment artifact {artifact.artifact_id!r} could not be read.",
                    hint="Use a visible alignment artifact with stable sealed content.",
                    stage="bio_tools_input_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"artifact_id": artifact.artifact_id},
                ) from exc
            if not content.startswith("# STOCKHOLM"):
                raise PipelineSdkFailure(
                    error_type="invalid_alignment",
                    message=f"Alignment artifact {artifact.artifact_id!r} is not valid Stockholm format.",
                    hint="Provide a FASTA/AFA or Stockholm alignment generated by MAFFT or another approved source.",
                    stage="bio_tools_input_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"artifact_id": artifact.artifact_id},
                )
            return
        self._validate_bio_tool_fasta_artifact(artifact, sdk_method=sdk_method)

    def _validate_bio_tool_hmm_artifact(
        self, artifact: SessionArtifactRecord, *, sdk_method: str
    ) -> None:
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if metadata_format != "hmm" and not artifact.relative_path.lower().endswith(
            ".hmm"
        ):
            raise PipelineSdkFailure(
                error_type="invalid_hmm",
                message=f"Artifact {artifact.artifact_id!r} must be an HMM artifact.",
                hint="Provide an HMM artifact generated by bio_tools.hmmbuild.",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={
                    "artifact_id": artifact.artifact_id,
                    "format": metadata_format,
                },
            )
        try:
            content = Path(artifact.storage_uri).read_text(encoding="utf-8")
        except OSError as exc:
            raise PipelineSdkFailure(
                error_type="artifact_not_available",
                message=f"HMM artifact {artifact.artifact_id!r} could not be read.",
                hint="Use a visible HMM artifact with stable sealed content.",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"artifact_id": artifact.artifact_id},
            ) from exc
        if not content.startswith("HMMER"):
            raise PipelineSdkFailure(
                error_type="invalid_hmm",
                message=f"Artifact {artifact.artifact_id!r} does not look like HMMER output.",
                hint="Regenerate the HMM with bio_tools.hmmbuild.",
                stage="bio_tools_input_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"artifact_id": artifact.artifact_id},
            )

    def _normalize_bio_output_dir(self, value: Any, *, sdk_method: str) -> str:
        raw = "" if value is None else str(value).strip()
        if not raw:
            raise PipelineSdkFailure(
                error_type="provider_output_path_invalid",
                message=f"{sdk_method} requires output_dir under /workspace/output.",
                hint="Pass output_dir='/workspace/output/<provider-specific-directory>'.",
                stage="bio_output_path_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        path = PurePosixPath(raw)
        parts = path.parts
        if (
            not path.is_absolute()
            or len(parts) < 4
            or parts[:3] != ("/", "workspace", "output")
            or any(part in {"", ".", ".."} for part in parts[3:])
            or any(char in raw for char in ("\\", "\n", "\r", "\0"))
        ):
            raise PipelineSdkFailure(
                error_type="provider_output_path_invalid",
                message=f"{sdk_method} output_dir {raw!r} is outside /workspace/output.",
                hint="Use a lexical sandbox output path such as /workspace/output/bio/ncbi.",
                stage="bio_output_path_validation",
                retryable=False,
                sdk_method=sdk_method,
                details={"output_dir": raw},
            )
        return PurePosixPath(*parts[3:]).as_posix()

    def _pipeline_bio_covered_by_approved_plan(
        self, *, pipeline: dict[str, Any], method: str
    ) -> bool:
        plan = dict(pipeline.get("execution_plan") or {})
        if not plan or pipeline.get("approved_plan_digest") != plan.get("plan_digest"):
            return False
        return any(
            operation.get("method") == method
            and int(operation.get("max_calls") or 0) > 0
            for operation in list(plan.get("bio_operations") or [])
        )

    def _pipeline_bio_tool_covered_by_approved_plan(
        self, *, pipeline: dict[str, Any], method: str
    ) -> bool:
        plan = dict(pipeline.get("execution_plan") or {})
        if not plan or pipeline.get("approved_plan_digest") != plan.get("plan_digest"):
            return False
        return any(
            operation.get("method") == method
            and operation.get("selected_backend") == "hpc"
            and int(operation.get("max_calls") or 0) > 0
            for operation in list(plan.get("bio_tool_operations") or [])
        )

    def _consume_approved_plan_operation_call(
        self,
        *,
        invocation: EngineInvocation,
        method: str,
        operation_group: str,
    ) -> int:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        plan = dict(pipeline.get("execution_plan") or {})
        if not plan or pipeline.get("approved_plan_digest") != plan.get("plan_digest"):
            raise PipelineSdkFailure(
                error_type="execution_plan_not_approved",
                message=f"{method} is not covered by the currently approved execution plan.",
                hint="Request approval for the changed operation before executing it.",
                stage="execution_plan_quota",
                retryable=False,
                sdk_method=method,
            )
        planned_operation = next(
            (
                operation
                for operation in list(plan.get(operation_group) or [])
                if operation.get("method") == method
            ),
            None,
        )
        max_calls = (
            0
            if planned_operation is None
            else int(planned_operation.get("max_calls") or 0)
        )
        if invocation.input_ref is None:
            consumed, allowed = 0, False
        else:
            consumed, allowed = (
                self.repositories.engine_documents.consume_pipeline_operation_call(
                    document_id=invocation.input_ref,
                    method=method,
                    max_calls=max_calls,
                )
            )
        if not allowed:
            raise PipelineSdkFailure(
                error_type="execution_plan_quota_exceeded",
                message=f"{method} exceeded the approved execution-plan call bound.",
                hint="Create and approve a new bounded plan with the required operation count.",
                stage="execution_plan_quota",
                retryable=False,
                sdk_method=method,
                details={
                    "method": method,
                    "max_calls": max_calls,
                    "consumed_calls": consumed,
                },
            )
        return consumed

    def _bio_adapter_approval_envelope(
        self,
        *,
        method: str,
        params: dict[str, Any],
        route_policy: dict[str, Any],
        output_dir_relative: str,
    ) -> dict[str, Any]:
        return {
            "adapter_envelope_schema_version": "s12.adapter_envelope.v1",
            "sdk_module": route_policy.get("sdk_module") or "bio",
            "function_name": route_policy.get("function_name")
            or method.rsplit(".", 1)[-1],
            "route_policy_id": route_policy["route_policy_id"],
            "selected_backend": route_policy.get("selected_backend"),
            "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
            "provider_config_digest": route_policy.get("provider_config_digest"),
            "resource_estimate": self._planned_bio_quota_estimate(method),
            "expected_outputs": self._planned_bio_expected_outputs(method),
            "approval_requirement": route_policy.get("approval_requirement")
            or {"required": True},
            "planned_output_path_summary": {
                "output_dir": f"/workspace/output/{output_dir_relative}"
            },
            "params_digest": hashlib.sha256(
                json.dumps(params, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
        }

    def _bio_tool_adapter_approval_envelope(
        self,
        *,
        method: str,
        params: dict[str, Any],
        route_policy: dict[str, Any],
        hpc_workspace_id: str,
        stage_refs: list[dict[str, Any]],
        declared_outputs: list[dict[str, Any]],
        resource_estimate: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "adapter_envelope_schema_version": "s12.adapter_envelope.v1",
            "sdk_module": "bio_tools",
            "function_name": method.removeprefix("bio_tools."),
            "route_policy_id": route_policy["route_policy_id"],
            "selected_backend": route_policy.get("selected_backend"),
            "route_reason": route_policy.get("route_reason"),
            "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
            "toolchain_id": route_policy.get("toolchain_id"),
            "resource_estimate": dict(resource_estimate),
            "expected_outputs": [dict(item) for item in declared_outputs],
            "declared_outputs": [dict(item) for item in declared_outputs],
            "approval_requirement": route_policy.get("approval_requirement")
            or {"required": True},
            "hpc_workspace_id": hpc_workspace_id,
            "stage_refs": [dict(item) for item in stage_refs],
            "planned_fetch_intent": True,
            "params_digest": hashlib.sha256(
                json.dumps(
                    params, sort_keys=True, separators=(",", ":"), default=str
                ).encode("utf-8")
            ).hexdigest(),
        }

    def _record_pipeline_adapter_approval_envelope(
        self,
        *,
        invocation: EngineInvocation,
        operation_key: str,
        envelope: dict[str, Any],
        approval_source: str,
    ) -> None:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        envelopes = dict(pipeline.get("adapter_approval_envelopes") or {})
        if operation_key in envelopes:
            return
        envelopes[operation_key] = {
            **dict(envelope),
            "approval_source": approval_source,
            "approved_plan_digest": pipeline.get("approved_plan_digest"),
        }
        self._update_pipeline_document(
            invocation, {"adapter_approval_envelopes": envelopes}
        )

    def _bio_provider_request_id(
        self,
        *,
        invocation: EngineInvocation,
        operation_key: str,
        output_dir_relative: str,
        retrieved_at: str,
    ) -> str:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "invocation_id": invocation.invocation_id,
                    "operation_key": operation_key,
                    "output_dir": output_dir_relative,
                    "retrieved_at": retrieved_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"provider_req_{digest}"

    def _sandbox_bio_provider_request_id(
        self,
        *,
        operation: ControlledOperation,
        output_dir_relative: str,
        retrieved_at: str,
    ) -> str:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "operation_id": operation.operation_id,
                    "operation_digest": operation.operation_digest,
                    "sandbox_run_id": operation.sandbox_run_id,
                    "output_dir": output_dir_relative,
                    "retrieved_at": retrieved_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"provider_req_{digest}"

    def _bio_request_metadata(
        self,
        *,
        invocation: EngineInvocation,
        pipeline: dict[str, Any],
        method: str,
        params: dict[str, Any],
        operation_key: str,
        output_dir_relative: str,
        provider_request_id: str,
        route_policy: dict[str, Any],
        retrieved_at: str,
    ) -> dict[str, Any]:
        return {
            "pipeline_invocation_id": invocation.invocation_id,
            "sdk_method": method,
            "provider": BIO_PROVIDER_NAMES.get(method, "unknown"),
            "provider_request_id": provider_request_id,
            "route_policy_id": route_policy["route_policy_id"],
            "selected_backend": route_policy.get("selected_backend"),
            "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
            "provider_config_digest": route_policy.get("provider_config_digest"),
            "evidence_ref": route_policy.get("evidence_ref"),
            "parameter_inventory_ref": route_policy.get("parameter_inventory_ref"),
            "approval_requirement": dict(
                route_policy.get("approval_requirement") or {}
            ),
            "operation_key": operation_key,
            "operation_digest": hashlib.sha256(
                json.dumps(
                    {"method": method, "params": params},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "params": _sanitize_provider_value(params),
            "output_dir": f"/workspace/output/{output_dir_relative}",
            "output_dir_relative": output_dir_relative,
            "retrieved_at": retrieved_at,
            "code_digest": pipeline.get("code_digest"),
            "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
            "source_code_digest": pipeline.get("source_code_digest"),
            "source_code_version": pipeline.get("source_code_version"),
            "pipeline_step_id": operation_key,
            "input_artifact_ids": list(
                (pipeline.get("inputs") or {}).get("artifact_ids") or []
            ),
            "preprocess_artifact_ids": list(
                pipeline.get("preprocess_artifact_ids") or []
            ),
        }

    def _sandbox_bio_request_metadata(
        self,
        *,
        operation: ControlledOperation,
        method: str,
        params: dict[str, Any],
        output_dir_relative: str,
        provider_request_id: str,
        route_policy: dict[str, Any],
        retrieved_at: str,
    ) -> dict[str, Any]:
        return {
            "sandbox_run_id": operation.sandbox_run_id,
            "sandbox_workspace_id": operation.sandbox_workspace_id,
            "controlled_operation_id": operation.operation_id,
            "sdk_method": method,
            "provider": BIO_PROVIDER_NAMES.get(method, "unknown"),
            "provider_request_id": provider_request_id,
            "route_policy_id": route_policy["route_policy_id"],
            "selected_backend": route_policy.get("selected_backend"),
            "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
            "provider_config_digest": route_policy.get("provider_config_digest"),
            "evidence_ref": route_policy.get("evidence_ref"),
            "parameter_inventory_ref": route_policy.get("parameter_inventory_ref"),
            "approval_requirement": dict(
                route_policy.get("approval_requirement") or {}
            ),
            "operation_key": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "params_digest": operation.params_digest,
            "params": _sanitize_provider_value(params),
            "output_dir": f"/workspace/output/{output_dir_relative}",
            "output_dir_relative": output_dir_relative,
            "retrieved_at": retrieved_at,
            "source_code_artifact_id": operation.source_snapshot_artifact_id,
            "source_code_digest": operation.source_snapshot_digest,
            "source_code_version": None,
            "pipeline_step_id": operation.operation_id,
            "input_artifact_ids": list(operation.input_artifact_ids),
            "preprocess_artifact_ids": [],
        }

    def _bio_provider_request_draft(
        self, request_metadata: dict[str, Any]
    ) -> BioArtifactDraft:
        payload = {
            "provider_request_id": request_metadata.get("provider_request_id"),
            "operation_id": request_metadata.get("operation_key"),
            "operation_digest": request_metadata.get("operation_digest"),
            "sdk_method": request_metadata.get("sdk_method"),
            "route_policy_id": request_metadata.get("route_policy_id"),
            "selected_backend": request_metadata.get("selected_backend"),
            "runtime_packaging_id": request_metadata.get("runtime_packaging_id"),
            "provider_config_digest": request_metadata.get("provider_config_digest"),
            "params": request_metadata.get("params"),
            "output_dir": request_metadata.get("output_dir"),
            "source_code_artifact_id": request_metadata.get("source_code_artifact_id"),
            "source_code_digest": request_metadata.get("source_code_digest"),
            "input_artifact_ids": list(
                request_metadata.get("input_artifact_ids") or []
            ),
            "preprocess_artifact_ids": list(
                request_metadata.get("preprocess_artifact_ids") or []
            ),
            "approval_requirement": request_metadata.get("approval_requirement"),
            "requested_at": request_metadata.get("retrieved_at"),
        }
        return BioArtifactDraft(
            relative_path="provider_request.json",
            kind=ArtifactKind.RESULT,
            title="provider_request.json",
            content=_json_text(_sanitize_provider_value(payload)),
            format="json",
            metadata={"format": "json", "transcript_file": "provider_request.json"},
        )

    def _bio_provider_observation_draft(
        self,
        *,
        request_metadata: dict[str, Any],
        result: BioSdkResult | None,
        warnings: list[dict[str, Any]],
        error: dict[str, Any] | None,
    ) -> BioArtifactDraft:
        payload = {
            "provider_request_id": request_metadata.get("provider_request_id"),
            "provider": request_metadata.get("provider"),
            "api_version": None if result is None else result.api_version,
            "route_policy_id": request_metadata.get("route_policy_id"),
            "provider_config_digest": request_metadata.get("provider_config_digest"),
            "status": "failed" if error else "completed",
            "summary": {} if result is None else dict(result.summary),
            "observation": {}
            if result is None
            else dict(result.provider_observation or {}),
            "warnings": _sanitize_provider_value(warnings),
            "canonical_error": _sanitize_provider_value(error) if error else None,
            "output_dir": request_metadata.get("output_dir"),
        }
        return BioArtifactDraft(
            relative_path="provider_observation.json",
            kind=ArtifactKind.RESULT,
            title="provider_observation.json",
            content=_json_text(_sanitize_provider_value(payload)),
            format="json",
            metadata={"format": "json", "transcript_file": "provider_observation.json"},
        )

    def _bio_provider_error_draft(
        self,
        *,
        request_metadata: dict[str, Any],
        failure: PipelineSdkFailure,
    ) -> BioArtifactDraft:
        payload = {
            "provider_request_id": request_metadata.get("provider_request_id"),
            "code": failure.error_type,
            "stage": failure.stage,
            "retryable": failure.retryable,
            "summary": failure.message,
            "hint": failure.hint,
            "details": _sanitize_provider_value(failure.details),
            "output_dir": request_metadata.get("output_dir"),
        }
        return BioArtifactDraft(
            relative_path="provider_error.json",
            kind=ArtifactKind.RESULT,
            title="provider_error.json",
            content=_json_text(payload),
            format="json",
            metadata={"format": "json", "transcript_file": "provider_error.json"},
        )

    def _normalize_bio_failure(self, failure: PipelineSdkFailure) -> PipelineSdkFailure:
        canonical = BIO_ERROR_CODE_MAP.get(failure.error_type, failure.error_type)
        if not canonical.startswith("provider_"):
            if canonical in {
                "missing_accessions",
                "invalid_accession",
                "missing_hmmer_database",
                "bio_quota_exceeded",
            }:
                canonical = "provider_invalid_request"
        stage = failure.stage
        if stage.startswith("bio_provider"):
            stage = stage.replace("bio_provider", "provider", 1)
        if stage.startswith("bio_result"):
            stage = stage.replace("bio_result", "provider_response", 1)
        return PipelineSdkFailure(
            error_type=canonical,
            message=failure.message,
            hint=failure.hint,
            stage=stage,
            retryable=failure.retryable,
            sdk_method=failure.sdk_method,
            hpc_failure=failure.hpc_failure,
            details=failure.details,
        )

    def _persist_bio_failure_transcript(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        failure: PipelineSdkFailure,
        output_dir_relative: str,
        request_metadata: dict[str, Any],
        request_draft: BioArtifactDraft,
    ) -> PipelineSdkFailure:
        if failure.stage in {
            "provider_config_validation",
            "provider_route_policy_validation",
            "bio_output_path_validation",
        }:
            return failure
        error_payload = {
            "code": failure.error_type,
            "stage": failure.stage,
            "retryable": failure.retryable,
            "summary": failure.message,
            "safe_diagnostics": _sanitize_provider_value(failure.details),
        }
        observation_draft = self._bio_provider_observation_draft(
            request_metadata=request_metadata,
            result=None,
            warnings=[],
            error=error_payload,
        )
        error_draft = self._bio_provider_error_draft(
            request_metadata=request_metadata, failure=failure
        )
        records = self._persist_bio_artifacts(
            session=session,
            invocation=invocation,
            output_dir_relative=output_dir_relative,
            operation_key=str(request_metadata["operation_key"]),
            drafts=(request_draft, observation_draft, error_draft),
            request_metadata=request_metadata,
        )
        details = {
            **failure.details,
            "provider_request_id": request_metadata.get("provider_request_id"),
            "diagnostic_artifact_ids": [record.artifact_id for record in records],
            "details_ref": f"artifact://{request_metadata.get('provider_request_id')}/provider_error.json",
        }
        return PipelineSdkFailure(
            error_type=failure.error_type,
            message=failure.message,
            hint=failure.hint,
            stage=failure.stage,
            retryable=failure.retryable,
            sdk_method=failure.sdk_method,
            hpc_failure=failure.hpc_failure,
            details=details,
        )

    def _persist_sandbox_bio_failure_transcript(
        self,
        *,
        operation: ControlledOperation,
        failure: PipelineSdkFailure,
        output_dir_relative: str,
        request_metadata: dict[str, Any],
        request_draft: BioArtifactDraft,
    ) -> PipelineSdkFailure:
        error_payload = {
            "code": failure.error_type,
            "stage": failure.stage,
            "retryable": failure.retryable,
            "summary": failure.message,
            "safe_diagnostics": _sanitize_provider_value(failure.details),
        }
        observation_draft = self._bio_provider_observation_draft(
            request_metadata=request_metadata,
            result=None,
            warnings=[],
            error=error_payload,
        )
        error_draft = self._bio_provider_error_draft(
            request_metadata=request_metadata,
            failure=failure,
        )
        records = self._persist_sandbox_bio_artifacts(
            operation=operation,
            output_dir_relative=output_dir_relative,
            operation_key=operation.operation_id,
            drafts=(request_draft, observation_draft, error_draft),
            request_metadata=request_metadata,
        )
        details = {
            **failure.details,
            "provider_request_id": request_metadata.get("provider_request_id"),
            "diagnostic_artifact_ids": [record.artifact_id for record in records],
            "diagnostic_artifact_refs": [
                {
                    "artifact_id": record.artifact_id,
                    "relative_path": record.relative_path,
                }
                for record in records
            ],
            "details_ref": (
                f"artifact://{request_metadata.get('provider_request_id')}"
                "/provider_error.json"
            ),
        }
        return PipelineSdkFailure(
            error_type=failure.error_type,
            message=failure.message,
            hint=failure.hint,
            stage=failure.stage,
            retryable=failure.retryable,
            sdk_method=failure.sdk_method,
            hpc_failure=failure.hpc_failure,
            details=details,
        )

    def _bio_transcript_manifest(
        self,
        *,
        output_dir_relative: str,
        records: tuple[SessionArtifactRecord, ...],
        provider_request_id: str,
        route_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider_request_id": provider_request_id,
            "route_policy_id": route_policy.get("route_policy_id"),
            "provider_config_digest": route_policy.get("provider_config_digest"),
            "output_dir": f"/workspace/output/{output_dir_relative}",
            "files": [
                {
                    "artifact_id": record.artifact_id,
                    "relative_path": record.relative_path,
                    "content_digest": dict(record.metadata or {}).get("content_digest"),
                    "kind": record.kind.value,
                    "format": dict(record.metadata or {}).get("format"),
                }
                for record in records
            ],
        }

    def _bio_primary_artifact_manifests(
        self,
        *,
        method: str,
        records: tuple[SessionArtifactRecord, ...],
    ) -> list[dict[str, Any]]:
        if method != "rcsb_pdb.download_structure":
            return []
        manifests: list[dict[str, Any]] = []
        for record in records:
            metadata = dict(record.metadata or {})
            if metadata.get("primary_output") is not True:
                continue
            provenance = (
                metadata.get("provider_provenance") or metadata.get("provenance") or {}
            )
            manifests.append(
                {
                    "artifact_id": record.artifact_id,
                    "kind": record.kind.value,
                    "relative_path": record.relative_path,
                    "format": metadata.get("format"),
                    "provider": metadata.get("provider"),
                    "external_id": metadata.get("external_id"),
                    "source_locator": metadata.get("source_locator"),
                    "content_digest": metadata.get("content_digest"),
                    "sealed_digest": metadata.get("sealed_digest"),
                    "provenance": _sanitize_provider_value(provenance),
                    "metadata": {
                        "provider": metadata.get("provider"),
                        "external_id": metadata.get("external_id"),
                        "format": metadata.get("format"),
                        "source_locator": metadata.get("source_locator"),
                        "content_digest": metadata.get("content_digest"),
                        "sealed_digest": metadata.get("sealed_digest"),
                        "provenance": _sanitize_provider_value(provenance),
                    },
                }
            )
        return manifests

    @staticmethod
    def _durable_hmmer_submitted_at(
        dispatch_receipt: dict[str, Any] | None,
        *,
        provider_request_id: str | None,
    ) -> str:
        if (
            not isinstance(dispatch_receipt, dict)
            or dispatch_receipt.get("schema_id")
            != EBI_HMMER_DURABLE_DISPATCH_RECEIPT_SCHEMA_ID
            or dispatch_receipt.get("provider_request_id") != provider_request_id
            or not isinstance(dispatch_receipt.get("submitted_at"), str)
        ):
            raise PipelineSdkFailure(
                error_type="provider_dispatch_receipt_invalid",
                message="Durable EBI HMMER dispatch receipt is missing or invalid.",
                hint="Preserve the execution for exact reconciliation; do not resubmit.",
                stage="provider_result_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer"},
            )
        submitted_at = str(dispatch_receipt["submitted_at"])
        try:
            parsed = datetime.fromisoformat(submitted_at)
        except ValueError as exc:
            raise PipelineSdkFailure(
                error_type="provider_dispatch_receipt_invalid",
                message="Durable EBI HMMER dispatch time is invalid.",
                hint="Preserve the execution for exact reconciliation; do not resubmit.",
                stage="provider_result_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer"},
            ) from exc
        if parsed.tzinfo is None:
            raise PipelineSdkFailure(
                error_type="provider_dispatch_receipt_invalid",
                message="Durable EBI HMMER dispatch time has no timezone.",
                hint="Preserve the execution for exact reconciliation; do not resubmit.",
                stage="provider_result_validation",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={"provider": "ebi_hmmer"},
            )
        return submitted_at

    def _execute_durable_hmmer_provider_phase(
        self,
        *,
        adapter: Any,
        phase: str,
        provider_request_id: str,
        hmm_artifact: SessionArtifactRecord,
        database: str,
        params: dict[str, Any],
        retrieved_at: str,
        dispatch_receipt: dict[str, Any] | None,
        observation_receipts: tuple[dict[str, Any], ...],
    ) -> BioSdkResult | dict[str, Any]:
        if phase not in {
            "dispatch",
            "poll",
            "materialize",
            "terminalize_failure",
            "timeout",
        }:
            raise self._durable_hmmer_receipt_failure(
                "provider_lifecycle_phase_invalid",
                "Durable EBI HMMER phase is invalid.",
            )
        if phase == "dispatch":
            if dispatch_receipt is not None or observation_receipts:
                raise self._durable_hmmer_receipt_failure(
                    "provider_dispatch_receipt_conflict",
                    "Durable EBI HMMER dispatch received preexisting receipt state.",
                )
            dispatch_callback = getattr(adapter, "dispatch_hmmer_search", None)
            if not callable(dispatch_callback):
                raise self._durable_hmmer_receipt_failure(
                    "provider_durable_lifecycle_unavailable",
                    "Configured EBI HMMER adapter has no durable dispatch capability.",
                )
            dispatch = dispatch_callback(
                hmm_artifact=hmm_artifact,
                database=database,
                params=params,
            )
            if not isinstance(dispatch, HmmerProviderDispatch):
                raise self._durable_hmmer_receipt_failure(
                    "provider_dispatch_receipt_invalid",
                    "EBI HMMER adapter returned an invalid dispatch receipt.",
                )
            submitted = datetime.fromisoformat(utc_now_iso())
            if submitted.tzinfo is None:
                submitted = submitted.replace(tzinfo=UTC)
            deadline = submitted + timedelta(seconds=dispatch.poll_timeout_seconds)
            receipt = {
                "schema_id": EBI_HMMER_DURABLE_DISPATCH_RECEIPT_SCHEMA_ID,
                "provider": "ebi_hmmer",
                "operation": "bio.hmmer_search",
                "provider_request_id": provider_request_id,
                "provider_job_id": dispatch.job_id,
                "submitted_at": submitted.isoformat(),
                "poll_deadline_at": deadline.isoformat(),
                "poll_interval_seconds": dispatch.poll_interval_seconds,
                "poll_timeout_seconds": dispatch.poll_timeout_seconds,
                "database": dispatch.normalized_database,
                "page_size": dispatch.page_size,
                "max_hits": dispatch.max_hits,
                "query_hmm_artifact_id": hmm_artifact.artifact_id,
                "query_hmm_digest": dispatch.query_hmm_digest,
                "request_payload_digest": dispatch.request_payload_digest,
                "submit_response": self._provider_http_response_receipt(
                    dispatch.submit_response
                ),
            }
            self._decode_durable_hmmer_dispatch_receipt(
                receipt,
                provider_request_id=provider_request_id,
            )
            return {
                "durable_provider_phase": "dispatch",
                "dispatch_receipt": receipt,
            }

        dispatch = self._decode_durable_hmmer_dispatch_receipt(
            dispatch_receipt,
            provider_request_id=provider_request_id,
        )
        dispatch_submitted_at = datetime.fromisoformat(
            str(dispatch_receipt["submitted_at"])  # type: ignore[index]
        )
        polls = self._decode_durable_hmmer_poll_receipts(
            observation_receipts,
            dispatch=dispatch,
            provider_request_id=provider_request_id,
            submitted_at=dispatch_submitted_at,
        )
        if phase == "poll":
            poll_callback = getattr(adapter, "poll_hmmer_search", None)
            if not callable(poll_callback):
                raise self._durable_hmmer_receipt_failure(
                    "provider_durable_lifecycle_unavailable",
                    "Configured EBI HMMER adapter has no durable poll capability.",
                )
            poll = poll_callback(
                job_id=dispatch.job_id,
                page_size=dispatch.page_size,
            )
            if not isinstance(poll, HmmerProviderPoll):
                raise self._durable_hmmer_receipt_failure(
                    "provider_observation_receipt_invalid",
                    "EBI HMMER adapter returned an invalid poll observation.",
                )
            status_class = self._durable_hmmer_status_class(poll.status)
            receipt = {
                "schema_id": EBI_HMMER_DURABLE_POLL_RECEIPT_SCHEMA_ID,
                "provider": "ebi_hmmer",
                "operation": "bio.hmmer_search",
                "provider_request_id": provider_request_id,
                "provider_job_id": dispatch.job_id,
                "observation_index": len(polls) + 1,
                "observed_at": utc_now_iso(),
                "status": poll.status,
                "status_class": status_class,
                "page_size": dispatch.page_size,
                "response": self._provider_http_response_receipt(poll.response),
            }
            self._decode_durable_hmmer_poll_receipts(
                (*observation_receipts, receipt),
                dispatch=dispatch,
                provider_request_id=provider_request_id,
                submitted_at=dispatch_submitted_at,
            )
            return {
                "durable_provider_phase": "poll",
                "status_class": status_class,
                "observation_receipt": receipt,
            }
        if phase == "timeout":
            deadline = datetime.fromisoformat(
                str(dispatch_receipt["poll_deadline_at"])  # type: ignore[index]
            )
            if deadline.tzinfo is None or datetime.now(tz=UTC) < deadline:
                raise self._durable_hmmer_receipt_failure(
                    "provider_timeout_not_reached",
                    "Durable EBI HMMER timeout was requested before its frozen deadline.",
                )
            raise PipelineSdkFailure(
                error_type="provider_timeout",
                message="EBI HMMER polling reached its frozen durable deadline.",
                hint="Inspect the exact accepted job before authorizing any new operation.",
                stage="provider_poll",
                retryable=True,
                sdk_method="bio.hmmer_search",
                details={
                    "provider": "ebi_hmmer",
                    "job_id": dispatch.job_id,
                    "last_status": None if not polls else polls[-1].status,
                    "poll_deadline_at": deadline.isoformat(),
                },
            )
        if not polls:
            raise self._durable_hmmer_receipt_failure(
                "provider_observation_missing",
                "Durable EBI HMMER terminal phase has no poll observation.",
            )
        terminal_class = self._durable_hmmer_status_class(polls[-1].status)
        if phase == "terminalize_failure":
            if terminal_class != "terminal_failure":
                raise self._durable_hmmer_receipt_failure(
                    "provider_terminal_status_invalid",
                    "Durable EBI HMMER failure phase has no terminal failure status.",
                )
            raise PipelineSdkFailure(
                error_type="provider_invalid_request",
                message="EBI HMMER job did not complete successfully.",
                hint="Inspect provider_error.json before authorizing a new operation.",
                stage="provider_poll",
                retryable=False,
                sdk_method="bio.hmmer_search",
                details={
                    "provider": "ebi_hmmer",
                    "job_id": dispatch.job_id,
                    "job_status": polls[-1].status,
                    "job_payload": _sanitize_provider_value(polls[-1].payload),
                },
            )
        if terminal_class != "terminal_success":
            raise self._durable_hmmer_receipt_failure(
                "provider_terminal_status_invalid",
                "Durable EBI HMMER materialization has no terminal success status.",
            )
        materialize_callback = getattr(adapter, "materialize_hmmer_search", None)
        if not callable(materialize_callback):
            raise self._durable_hmmer_receipt_failure(
                "provider_durable_lifecycle_unavailable",
                "Configured EBI HMMER adapter has no durable materialization capability.",
            )
        return materialize_callback(
            hmm_artifact=hmm_artifact,
            database=database,
            params=params,
            retrieved_at=retrieved_at,
            dispatch=dispatch,
            polls=polls,
        )

    def _decode_durable_hmmer_dispatch_receipt(
        self,
        receipt: dict[str, Any] | None,
        *,
        provider_request_id: str,
    ) -> HmmerProviderDispatch:
        expected_fields = {
            "schema_id",
            "provider",
            "operation",
            "provider_request_id",
            "provider_job_id",
            "submitted_at",
            "poll_deadline_at",
            "poll_interval_seconds",
            "poll_timeout_seconds",
            "database",
            "page_size",
            "max_hits",
            "query_hmm_artifact_id",
            "query_hmm_digest",
            "request_payload_digest",
            "submit_response",
        }
        if not isinstance(receipt, dict) or set(receipt) != expected_fields:
            raise self._durable_hmmer_receipt_failure(
                "provider_dispatch_receipt_invalid",
                "Durable EBI HMMER dispatch receipt shape is invalid.",
            )
        job_id = receipt.get("provider_job_id")
        interval = receipt.get("poll_interval_seconds")
        timeout = receipt.get("poll_timeout_seconds")
        page_size = receipt.get("page_size")
        max_hits = receipt.get("max_hits")
        try:
            submitted = datetime.fromisoformat(str(receipt.get("submitted_at") or ""))
            deadline = datetime.fromisoformat(
                str(receipt.get("poll_deadline_at") or "")
            )
        except ValueError as exc:
            raise self._durable_hmmer_receipt_failure(
                "provider_dispatch_receipt_invalid",
                "Durable EBI HMMER dispatch receipt timestamps are invalid.",
            ) from exc
        if (
            receipt.get("schema_id")
            != EBI_HMMER_DURABLE_DISPATCH_RECEIPT_SCHEMA_ID
            or receipt.get("provider") != "ebi_hmmer"
            or receipt.get("operation") != "bio.hmmer_search"
            or receipt.get("provider_request_id") != provider_request_id
            or not isinstance(job_id, str)
            or not job_id
            or job_id != job_id.strip()
            or len(job_id.encode("utf-8")) > 4_096
            or isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or float(interval) <= 0
            or float(interval) > 300
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or float(timeout) <= 0
            or float(timeout) > 86_400
            or isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size <= 0
            or page_size > _HMMER_PAGE_SIZE_CAP
            or isinstance(max_hits, bool)
            or not isinstance(max_hits, int)
            or max_hits <= 0
            or max_hits > _HMMER_MAX_HITS_CAP
            or not isinstance(receipt.get("database"), str)
            or not isinstance(receipt.get("query_hmm_artifact_id"), str)
            or not _is_sha256_digest(str(receipt.get("query_hmm_digest") or ""))
            or not _is_sha256_digest(
                str(receipt.get("request_payload_digest") or "")
            )
            or submitted.tzinfo is None
            or deadline.tzinfo is None
            or deadline
            != submitted + timedelta(seconds=float(timeout))
        ):
            raise self._durable_hmmer_receipt_failure(
                "provider_dispatch_receipt_invalid",
                "Durable EBI HMMER dispatch receipt identity is invalid.",
            )
        response = self._provider_http_response_from_receipt(
            receipt.get("submit_response")
        )
        if _extract_ebi_hmmer_job_id(response.body) != job_id:
            raise self._durable_hmmer_receipt_failure(
                "provider_dispatch_receipt_invalid",
                "Durable EBI HMMER submit response does not match its job id.",
            )
        return HmmerProviderDispatch(
            job_id=job_id,
            submit_response=response,
            normalized_database=str(receipt["database"]),
            page_size=page_size,
            max_hits=max_hits,
            query_hmm_digest=str(receipt["query_hmm_digest"]),
            request_payload_digest=str(receipt["request_payload_digest"]),
            poll_interval_seconds=float(interval),
            poll_timeout_seconds=float(timeout),
        )

    def _decode_durable_hmmer_poll_receipts(
        self,
        receipts: tuple[dict[str, Any], ...],
        *,
        dispatch: HmmerProviderDispatch,
        provider_request_id: str,
        submitted_at: datetime,
    ) -> tuple[HmmerProviderPoll, ...]:
        expected_fields = {
            "schema_id",
            "provider",
            "operation",
            "provider_request_id",
            "provider_job_id",
            "observation_index",
            "observed_at",
            "status",
            "status_class",
            "page_size",
            "response",
        }
        decoded: list[HmmerProviderPoll] = []
        max_observation_count = (
            math.ceil(
                dispatch.poll_timeout_seconds / dispatch.poll_interval_seconds
            )
            + 1
        )
        if len(receipts) > max_observation_count:
            raise self._durable_hmmer_receipt_failure(
                "provider_observation_receipt_invalid",
                "Durable EBI HMMER poll history exceeds its frozen deadline bound.",
            )
        terminal_seen = False
        previous_observed_at = submitted_at
        for index, receipt in enumerate(receipts, start=1):
            if not isinstance(receipt, dict) or set(receipt) != expected_fields:
                raise self._durable_hmmer_receipt_failure(
                    "provider_observation_receipt_invalid",
                    "Durable EBI HMMER poll receipt shape is invalid.",
                )
            try:
                observed_at = datetime.fromisoformat(
                    str(receipt.get("observed_at") or "")
                )
            except ValueError as exc:
                raise self._durable_hmmer_receipt_failure(
                    "provider_observation_receipt_invalid",
                    "Durable EBI HMMER poll timestamp is invalid.",
                ) from exc
            status = str(receipt.get("status") or "")
            status_class = self._durable_hmmer_status_class(status)
            if (
                receipt.get("schema_id")
                != EBI_HMMER_DURABLE_POLL_RECEIPT_SCHEMA_ID
                or receipt.get("provider") != "ebi_hmmer"
                or receipt.get("operation") != "bio.hmmer_search"
                or receipt.get("provider_request_id") != provider_request_id
                or receipt.get("provider_job_id") != dispatch.job_id
                or receipt.get("observation_index") != index
                or receipt.get("status_class") != status_class
                or receipt.get("page_size") != dispatch.page_size
                or observed_at.tzinfo is None
                or observed_at < previous_observed_at
                or terminal_seen
            ):
                raise self._durable_hmmer_receipt_failure(
                    "provider_observation_receipt_invalid",
                    "Durable EBI HMMER poll receipt identity is invalid.",
                )
            response = self._provider_http_response_from_receipt(
                receipt.get("response")
            )
            try:
                payload = json.loads(response.body)
            except json.JSONDecodeError as exc:
                raise self._durable_hmmer_receipt_failure(
                    "provider_observation_receipt_invalid",
                    "Durable EBI HMMER poll response is not JSON.",
                ) from exc
            if (
                not isinstance(payload, dict)
                or str(payload.get("status") or "").upper() != status
            ):
                raise self._durable_hmmer_receipt_failure(
                    "provider_observation_receipt_invalid",
                    "Durable EBI HMMER poll payload does not match its status.",
                )
            decoded.append(
                HmmerProviderPoll(
                    job_id=dispatch.job_id,
                    page_size=dispatch.page_size,
                    status=status,
                    payload=payload,
                    response=response,
                )
            )
            previous_observed_at = observed_at
            terminal_seen = status_class != "nonterminal"
        return tuple(decoded)

    @staticmethod
    def _durable_hmmer_status_class(status: str) -> str:
        normalized = status.upper()
        if normalized in _HMMER_NONTERMINAL_JOB_STATUSES:
            return "nonterminal"
        if normalized in {"SUCCESS", "DONE"}:
            return "terminal_success"
        return "terminal_failure"

    @staticmethod
    def _provider_http_response_receipt(
        response: BioProviderHttpResponse,
    ) -> dict[str, Any]:
        return {
            "status_code": response.status_code,
            "headers": _sanitize_provider_headers(response.headers),
            "body_encoding": "base64",
            "body_base64": base64.b64encode(response.body_bytes).decode("ascii"),
            "body_digest": response.body_digest,
            "size_bytes": len(response.body_bytes),
            "url": response.url,
        }

    def _provider_http_response_from_receipt(
        self,
        value: Any,
    ) -> BioProviderHttpResponse:
        expected_fields = {
            "status_code",
            "headers",
            "body_encoding",
            "body_base64",
            "body_digest",
            "size_bytes",
            "url",
        }
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise self._durable_hmmer_receipt_failure(
                "provider_http_receipt_invalid",
                "Durable provider HTTP receipt shape is invalid.",
            )
        try:
            body_bytes = base64.b64decode(str(value.get("body_base64")), validate=True)
        except (TypeError, ValueError) as exc:
            raise self._durable_hmmer_receipt_failure(
                "provider_http_receipt_invalid",
                "Durable provider HTTP receipt body is not canonical base64.",
            ) from exc
        headers = value.get("headers")
        status_code = value.get("status_code")
        if (
            value.get("body_encoding") != "base64"
            or value.get("size_bytes") != len(body_bytes)
            or value.get("body_digest") != _sha256_bytes(body_bytes)
            or not isinstance(headers, dict)
            or headers != _sanitize_provider_headers(headers)
            or any(
                not isinstance(key, str) or not isinstance(item, str)
                for key, item in headers.items()
            )
            or isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or status_code < 100
            or status_code > 599
            or not isinstance(value.get("url"), str)
            or not str(value.get("url"))
        ):
            raise self._durable_hmmer_receipt_failure(
                "provider_http_receipt_invalid",
                "Durable provider HTTP receipt identity is invalid.",
            )
        return BioProviderHttpResponse(
            status_code=status_code,
            headers=dict(headers),
            body=body_bytes.decode("utf-8", errors="replace"),
            body_bytes=body_bytes,
            url=str(value["url"]),
        )

    @staticmethod
    def _durable_hmmer_receipt_failure(
        error_type: str,
        message: str,
    ) -> PipelineSdkFailure:
        return PipelineSdkFailure(
            error_type=error_type,
            message=message,
            hint="Preserve the accepted provider effect and reject replay.",
            stage="provider_result_validation",
            retryable=False,
            sdk_method="bio.hmmer_search",
            details={"provider": "ebi_hmmer"},
        )

    def _execute_sandbox_bio_provider_operation(
        self,
        *,
        operation: ControlledOperation,
        method: str,
        params: dict[str, Any],
        frozen_provider_request_id: str | None = None,
        durable_provider_phase: str | None = None,
        durable_provider_dispatch_receipt: dict[str, Any] | None = None,
        durable_provider_observation_receipts: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        route_policy = self._require_bio_route_policy(method)
        if operation.route_policy_id != route_policy["route_policy_id"]:
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} route policy does not match the approved S12 operation.",
                hint="Retry through the public SDK so route_policy_id and function name are consistent.",
                stage="provider_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "operation_id": operation.operation_id,
                    "operation_route_policy_id": operation.route_policy_id,
                    "expected_route_policy_id": route_policy["route_policy_id"],
                },
            )
        output_dir_relative = self._normalize_bio_output_dir(
            params.get("output_dir"), sdk_method=method
        )
        adapter = self.bio_adapter
        if adapter is None:
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} has no configured real bio provider adapter.",
                hint="Configure the Host bio provider adapter; do not rely on fixture provider success.",
                stage="provider_config_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy["route_policy_id"],
                    "selected_backend": route_policy["selected_backend"],
                    "provider_config_digest": route_policy["provider_config_digest"],
                },
            )
        if (
            isinstance(adapter, DeterministicBioDatabaseAdapter)
            and not self.allow_bio_fixture_adapter
        ):
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} resolved to the deterministic fixture bio adapter.",
                hint="Use a real Host provider adapter for product execution, or enable the fixture only in focused tests.",
                stage="provider_config_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy["route_policy_id"],
                    "selected_backend": "fixture",
                    "required_backend": route_policy["selected_backend"],
                },
            )
        if self.repositories.sessions.get(operation.session_id) is None:
            raise PipelineSdkFailure(
                error_type="adapter_execution_unavailable",
                message=f"Session {operation.session_id!r} is not available for sandbox adapter execution.",
                hint="Retry in an active session.",
                stage="adapter_context_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        if durable_provider_phase is not None and method != "bio.hmmer_search":
            raise PipelineSdkFailure(
                error_type="provider_lifecycle_phase_invalid",
                message="Durable provider phases are only supported for EBI HMMER.",
                hint="Use the ordinary durable provider route for this operation.",
                stage="provider_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        retrieved_at = (
            utc_now_iso()
            if durable_provider_phase in {None, "dispatch"}
            else self._durable_hmmer_submitted_at(
                durable_provider_dispatch_receipt,
                provider_request_id=frozen_provider_request_id,
            )
        )
        if (
            frozen_provider_request_id is not None
            and re.fullmatch(r"provider_req_[0-9a-f]{24}", frozen_provider_request_id)
            is None
        ):
            raise PipelineSdkFailure(
                error_type="provider_request_identity_invalid",
                message="Durable provider execution has an invalid frozen request identity.",
                hint="Do not dispatch; preserve the canonical execution for operator inspection.",
                stage="provider_route_policy_validation",
                retryable=False,
                sdk_method=method,
                details={"operation_id": operation.operation_id},
            )
        provider_request_id = frozen_provider_request_id or (
            self._sandbox_bio_provider_request_id(
                operation=operation,
                output_dir_relative=output_dir_relative,
                retrieved_at=retrieved_at,
            )
        )
        request_metadata = self._sandbox_bio_request_metadata(
            operation=operation,
            method=method,
            params=params,
            output_dir_relative=output_dir_relative,
            provider_request_id=provider_request_id,
            route_policy=route_policy,
            retrieved_at=retrieved_at,
        )
        request_draft = self._bio_provider_request_draft(request_metadata)
        try:
            if method == "bio.ncbi_fetch_proteins":
                result = adapter.ncbi_fetch_proteins(
                    accessions=tuple(
                        str(value) for value in list(params.get("accessions") or [])
                    ),
                    fields=tuple(
                        str(value) for value in list(params.get("fields") or [])
                    ),
                    retrieved_at=retrieved_at,
                )
            elif method == "bio.uniprot_fetch":
                batch_size_value = params.get("batch_size")
                batch_size = _exact_optional_uniprot_batch_size(
                    batch_size_value,
                    sdk_method=method,
                )
                result = adapter.uniprot_fetch(
                    accessions=tuple(
                        str(value) for value in list(params.get("accessions") or [])
                    ),
                    fields=tuple(
                        str(value) for value in list(params.get("fields") or [])
                    ),
                    batch_size=batch_size,
                    retrieved_at=retrieved_at,
                    source_sequence_identities=params.get("source_sequence_identities"),
                    sequence_mismatch_choices=params.get("sequence_mismatch_choices"),
                )
            elif method == "rcsb_pdb.download_structure":
                result = adapter.rcsb_download_structure(
                    pdb_id=str(params.get("pdb_id") or ""),
                    file_format=str(params.get("format") or "pdb"),
                    retrieved_at=retrieved_at,
                )
            elif method == "bio.hmmer_search":
                hmm_artifact_id = str(params.get("hmm_artifact_id") or "")
                hmm_artifact = self.repositories.artifacts.get(hmm_artifact_id)
                if (
                    hmm_artifact is None
                    or hmm_artifact.session_id != operation.session_id
                ):
                    raise PipelineSdkFailure(
                        error_type="invalid_hmm_artifact",
                        message=f"HMM artifact {hmm_artifact_id!r} is not available in this session.",
                        hint="Pass an existing HMM artifact id produced or uploaded in this session.",
                        stage="bio_input_validation",
                        retryable=False,
                        sdk_method=method,
                        details={"hmm_artifact_id": hmm_artifact_id},
                    )
                hmm_format = str(
                    (hmm_artifact.metadata or {}).get("format") or ""
                ).lower()
                if (
                    hmm_format != "hmm"
                    and not hmm_artifact.relative_path.lower().endswith(".hmm")
                ):
                    raise PipelineSdkFailure(
                        error_type="invalid_hmm_artifact",
                        message=f"HMM artifact {hmm_artifact_id!r} must declare format=hmm or use a .hmm relative path.",
                        hint="Pass an HMM artifact produced by bio_tools.hmmbuild or an uploaded HMM file.",
                        stage="bio_input_validation",
                        retryable=False,
                        sdk_method=method,
                        details={
                            "hmm_artifact_id": hmm_artifact_id,
                            "format": hmm_format,
                        },
                    )
                if durable_provider_phase is None:
                    result = adapter.hmmer_search(
                        hmm_artifact=hmm_artifact,
                        database=str(params.get("database") or ""),
                        params=dict(params.get("params") or {}),
                        retrieved_at=retrieved_at,
                    )
                else:
                    durable_result = self._execute_durable_hmmer_provider_phase(
                        adapter=adapter,
                        phase=durable_provider_phase,
                        provider_request_id=provider_request_id,
                        hmm_artifact=hmm_artifact,
                        database=str(params.get("database") or ""),
                        params=dict(params.get("params") or {}),
                        retrieved_at=retrieved_at,
                        dispatch_receipt=durable_provider_dispatch_receipt,
                        observation_receipts=(
                            durable_provider_observation_receipts
                        ),
                    )
                    if isinstance(durable_result, dict):
                        return durable_result
                    result = durable_result
            else:
                raise PipelineSdkFailure(
                    error_type="provider_not_configured",
                    message=f"Unsupported bio SDK operation {method!r}.",
                    hint="Use one of the registered bio provider SDK functions.",
                    stage="provider_route_policy_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"method": method},
                )
        except PipelineSdkFailure as exc:
            normalized_failure = self._normalize_bio_failure(exc)
            if durable_provider_phase in {"dispatch", "poll"} or (
                durable_provider_phase == "materialize"
                and normalized_failure.retryable
            ):
                raise normalized_failure from exc
            raise self._persist_sandbox_bio_failure_transcript(
                operation=operation,
                failure=normalized_failure,
                output_dir_relative=output_dir_relative,
                request_metadata=request_metadata,
                request_draft=request_draft,
            ) from exc
        observation_draft = self._bio_provider_observation_draft(
            request_metadata=request_metadata,
            result=result,
            warnings=list(result.warnings),
            error=None,
        )
        records = self._persist_sandbox_bio_artifacts(
            operation=operation,
            output_dir_relative=output_dir_relative,
            operation_key=operation.operation_id,
            drafts=(request_draft, *result.artifacts, observation_draft),
            request_metadata=request_metadata,
        )
        transcript_manifest = self._bio_transcript_manifest(
            output_dir_relative=output_dir_relative,
            records=records,
            provider_request_id=provider_request_id,
            route_policy=route_policy,
        )
        bounded_summary = {
            **dict(result.summary),
            "transcript_manifest": transcript_manifest,
        }
        primary_artifacts = self._bio_primary_artifact_manifests(
            method=method, records=records
        )
        if primary_artifacts:
            bounded_summary["artifacts"] = primary_artifacts
        adapter_result = {
            "status": RunStatus.SUCCEEDED.value,
            "provider_request_id": provider_request_id,
            "registered_artifact_ids": [record.artifact_id for record in records],
            "output_artifact_ids": [record.artifact_id for record in records],
            "validation_results": {
                record.artifact_id: dict(
                    (record.metadata or {}).get("validation") or {}
                )
                for record in records
            },
            "bounded_summary": bounded_summary,
            "warnings": list(result.warnings),
            "safe_diagnostics_ref": f"artifact://{provider_request_id}/provider_observation.json",
        }
        self._emit(
            "sandbox.adapter_operation.completed",
            {
                "operation_id": operation.operation_id,
                "sandbox_run_id": operation.sandbox_run_id,
                "operation": method,
                "provider_request_id": provider_request_id,
                "artifact_ids": [record.artifact_id for record in records],
                "warning_count": len(result.warnings),
            },
        )
        return {"adapter_result": adapter_result, "result_summary": bounded_summary}

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
        route_policy = self._require_bio_route_policy(method)
        output_dir_relative = self._normalize_bio_output_dir(
            params.get("output_dir"), sdk_method=method
        )
        adapter_approval_envelope = self._bio_adapter_approval_envelope(
            method=method,
            params=params,
            route_policy=route_policy,
            output_dir_relative=output_dir_relative,
        )
        covered_by_approved_plan = self._pipeline_bio_covered_by_approved_plan(
            pipeline=pipeline,
            method=method,
        )
        approved_operation_keys = set(pipeline.get("approved_operation_keys") or [])
        if (
            operation_key not in approved_operation_keys
            and not covered_by_approved_plan
        ):
            approval = self._request_pipeline_approval(
                invocation=invocation,
                method=method,
                params=params,
                operation_key=operation_key,
            )
            raise PipelineApprovalRequired(approval)
        if covered_by_approved_plan:
            self._record_pipeline_adapter_approval_envelope(
                invocation=invocation,
                operation_key=operation_key,
                envelope=adapter_approval_envelope,
                approval_source="execution_pipeline_plan",
            )
        elif operation_key in approved_operation_keys:
            self._record_pipeline_adapter_approval_envelope(
                invocation=invocation,
                operation_key=operation_key,
                envelope=adapter_approval_envelope,
                approval_source="execution_pipeline_operation",
            )
        adapter = self.bio_adapter
        if adapter is None:
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} has no configured real bio provider adapter.",
                hint="Configure the Host bio provider adapter; do not rely on fixture provider success.",
                stage="provider_config_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy["route_policy_id"],
                    "selected_backend": route_policy["selected_backend"],
                    "provider_config_digest": route_policy["provider_config_digest"],
                },
            )
        if (
            isinstance(adapter, DeterministicBioDatabaseAdapter)
            and not self.allow_bio_fixture_adapter
        ):
            raise PipelineSdkFailure(
                error_type="provider_not_configured",
                message=f"{method} resolved to the deterministic fixture bio adapter.",
                hint="Use a real Host provider adapter for product execution, or enable the fixture only in focused tests.",
                stage="provider_config_validation",
                retryable=False,
                sdk_method=method,
                details={
                    "route_policy_id": route_policy["route_policy_id"],
                    "selected_backend": "fixture",
                    "required_backend": route_policy["selected_backend"],
                },
            )
        if covered_by_approved_plan:
            self._consume_approved_plan_operation_call(
                invocation=invocation,
                method=method,
                operation_group="bio_operations",
            )
        retrieved_at = utc_now_iso()
        provider_request_id = self._bio_provider_request_id(
            invocation=invocation,
            operation_key=operation_key,
            output_dir_relative=output_dir_relative,
            retrieved_at=retrieved_at,
        )
        request_metadata = self._bio_request_metadata(
            invocation=invocation,
            pipeline=pipeline,
            method=method,
            params=params,
            operation_key=operation_key,
            output_dir_relative=output_dir_relative,
            provider_request_id=provider_request_id,
            route_policy=route_policy,
            retrieved_at=retrieved_at,
        )
        request_draft = self._bio_provider_request_draft(request_metadata)
        if method == "bio.ncbi_fetch_proteins":
            try:
                result = adapter.ncbi_fetch_proteins(
                    accessions=tuple(
                        str(value) for value in list(params.get("accessions") or [])
                    ),
                    fields=tuple(
                        str(value) for value in list(params.get("fields") or [])
                    ),
                    retrieved_at=retrieved_at,
                )
            except PipelineSdkFailure as exc:
                raise self._persist_bio_failure_transcript(
                    session=session,
                    invocation=invocation,
                    failure=self._normalize_bio_failure(exc),
                    output_dir_relative=output_dir_relative,
                    request_metadata=request_metadata,
                    request_draft=request_draft,
                ) from exc
        elif method == "rcsb_pdb.download_structure":
            try:
                result = adapter.rcsb_download_structure(
                    pdb_id=str(params.get("pdb_id") or ""),
                    file_format=str(params.get("format") or "pdb"),
                    retrieved_at=retrieved_at,
                )
            except PipelineSdkFailure as exc:
                raise self._persist_bio_failure_transcript(
                    session=session,
                    invocation=invocation,
                    failure=self._normalize_bio_failure(exc),
                    output_dir_relative=output_dir_relative,
                    request_metadata=request_metadata,
                    request_draft=request_draft,
                ) from exc
        elif method == "bio.uniprot_fetch":
            batch_size_value = params.get("batch_size")
            batch_size = _exact_optional_uniprot_batch_size(
                batch_size_value,
                sdk_method=method,
            )
            try:
                result = adapter.uniprot_fetch(
                    accessions=tuple(
                        str(value) for value in list(params.get("accessions") or [])
                    ),
                    fields=tuple(
                        str(value) for value in list(params.get("fields") or [])
                    ),
                    batch_size=batch_size,
                    retrieved_at=retrieved_at,
                    source_sequence_identities=params.get("source_sequence_identities"),
                    sequence_mismatch_choices=params.get("sequence_mismatch_choices"),
                )
            except PipelineSdkFailure as exc:
                raise self._persist_bio_failure_transcript(
                    session=session,
                    invocation=invocation,
                    failure=self._normalize_bio_failure(exc),
                    output_dir_relative=output_dir_relative,
                    request_metadata=request_metadata,
                    request_draft=request_draft,
                ) from exc
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
            if hmm_format != "hmm" and not hmm_artifact.relative_path.lower().endswith(
                ".hmm"
            ):
                raise PipelineSdkFailure(
                    error_type="invalid_hmm_artifact",
                    message=f"HMM artifact {hmm_artifact_id!r} must declare format=hmm or use a .hmm relative path.",
                    hint="Pass an HMM artifact produced by bio_tools.hmmbuild or an uploaded HMM file.",
                    stage="bio_input_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"hmm_artifact_id": hmm_artifact_id, "format": hmm_format},
                )
            try:
                result = adapter.hmmer_search(
                    hmm_artifact=hmm_artifact,
                    database=str(params.get("database") or ""),
                    params=dict(params.get("params") or {}),
                    retrieved_at=retrieved_at,
                )
            except PipelineSdkFailure as exc:
                raise self._persist_bio_failure_transcript(
                    session=session,
                    invocation=invocation,
                    failure=self._normalize_bio_failure(exc),
                    output_dir_relative=output_dir_relative,
                    request_metadata=request_metadata,
                    request_draft=request_draft,
                ) from exc
        else:
            raise ValueError(f"unsupported bio SDK operation {method!r}")
        observation_draft = self._bio_provider_observation_draft(
            request_metadata=request_metadata,
            result=result,
            warnings=list(result.warnings),
            error=None,
        )
        records = self._persist_bio_artifacts(
            session=session,
            invocation=invocation,
            output_dir_relative=output_dir_relative,
            operation_key=operation_key,
            drafts=(request_draft, *result.artifacts, observation_draft),
            request_metadata=request_metadata,
        )
        transcript_manifest = self._bio_transcript_manifest(
            output_dir_relative=output_dir_relative,
            records=records,
            provider_request_id=provider_request_id,
            route_policy=route_policy,
        )
        bounded_summary = {
            **dict(result.summary),
            "transcript_manifest": transcript_manifest,
        }
        primary_artifacts = self._bio_primary_artifact_manifests(
            method=method, records=records
        )
        if primary_artifacts:
            bounded_summary["artifacts"] = primary_artifacts
        adapter_result_envelope = {
            "status": RunStatus.SUCCEEDED.value,
            "provider_request_id": provider_request_id,
            "registered_artifact_ids": [record.artifact_id for record in records],
            "output_artifact_ids": [record.artifact_id for record in records],
            "validation_results": {
                record.artifact_id: dict(
                    (record.metadata or {}).get("validation") or {}
                )
                for record in records
            },
            "bounded_summary": bounded_summary,
            "warnings": list(result.warnings),
            "safe_diagnostics_ref": f"artifact://{provider_request_id}/provider_observation.json",
        }
        payload = {
            "tool_id": method,
            "provider": result.provider,
            "status": RunStatus.SUCCEEDED.value,
            "operation_key": operation_key,
            "provider_request_id": provider_request_id,
            "summary": result.summary,
            "bounded_summary": bounded_summary,
            "adapter_result_envelope": adapter_result_envelope,
            "warnings": list(result.warnings),
            "artifact_count": len(records),
            "artifact_ids": [record.artifact_id for record in records],
            "artifacts": [project_artifact_for_agent(record) for record in records],
        }
        self._record_pipeline_completed_operation(invocation, operation_key, payload)
        self._append_pipeline_list(
            invocation, "bio_artifact_ids", [record.artifact_id for record in records]
        )
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

    def _bio_tool_slot_names(self, method: str) -> tuple[str, ...]:
        return {
            "bio_tools.cdhit": ("input_fasta",),
            "bio_tools.mafft": ("input_fasta",),
            "bio_tools.hmmbuild": ("alignment",),
            "bio_tools.hmmalign": ("hmm", "fasta"),
            "bio_tools.hmmer_search_cli": ("hmm", "target_fasta"),
        }.get(method, ())

    def _bio_tool_stage_refs(
        self, *, method: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            dict(params.get(slot_name) or {})
            for slot_name in self._bio_tool_slot_names(method)
        ]

    def _bio_tool_runner_params(
        self, *, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        nested = dict(params.get("params") or {})
        if nested:
            raise PipelineSdkFailure(
                error_type="forbidden_param",
                message=f"{method} does not accept raw or nested params in S14.",
                hint="Use the typed SDK parameters for this tool; raw args, paths and passthrough params are forbidden.",
                stage="bio_tools_params_validation",
                retryable=False,
                sdk_method=method,
                details={"forbidden_params": sorted(nested)},
            )
        if method == "bio_tools.cdhit":
            try:
                identity = float(params.get("identity"))
            except (TypeError, ValueError) as exc:
                raise PipelineSdkFailure(
                    error_type="invalid_params",
                    message="bio_tools.cdhit identity must be numeric.",
                    hint="Retry with an identity threshold such as 0.9.",
                    stage="bio_tools_params_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"identity": params.get("identity")},
                ) from exc
            if identity <= 0 or identity > 1:
                raise PipelineSdkFailure(
                    error_type="invalid_params",
                    message="bio_tools.cdhit identity must be in the range (0, 1].",
                    hint="Retry with a CD-HIT identity threshold such as 0.85 or 0.9.",
                    stage="bio_tools_params_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"identity": identity},
                )
            mode = str(params.get("mode") or "protein")
            if mode not in {"protein", "reference", "candidate"}:
                raise PipelineSdkFailure(
                    error_type="invalid_params",
                    message=f"bio_tools.cdhit mode {mode!r} is not supported in S14.",
                    hint="Use mode='protein' for generic protein clustering, mode='reference' for AOX reference clustering, or mode='candidate' for AOX candidate clustering.",
                    stage="bio_tools_params_validation",
                    retryable=False,
                    sdk_method=method,
                    details={"mode": mode},
                )
            return {"identity": identity, "mode": mode}
        return {}

    def _validate_bio_tool_inputs(
        self, *, method: str, artifacts_by_slot: dict[str, SessionArtifactRecord]
    ) -> None:
        if method == "bio_tools.cdhit":
            self._validate_bio_tool_fasta_artifact(
                artifacts_by_slot["input_fasta"], sdk_method=method
            )
            return
        if method == "bio_tools.mafft":
            self._validate_bio_tool_fasta_artifact(
                artifacts_by_slot["input_fasta"], sdk_method=method, min_records=2
            )
            return
        if method == "bio_tools.hmmbuild":
            self._validate_bio_tool_alignment_artifact(
                artifacts_by_slot["alignment"], sdk_method=method
            )
            return
        if method == "bio_tools.hmmalign":
            self._validate_bio_tool_hmm_artifact(
                artifacts_by_slot["hmm"], sdk_method=method
            )
            self._validate_bio_tool_fasta_artifact(
                artifacts_by_slot["fasta"], sdk_method=method
            )
            return
        raise ValueError(f"unsupported bio tools SDK operation {method!r}")

    def _bio_tool_runner_failure(
        self, *, method: str, result: dict[str, Any]
    ) -> PipelineSdkFailure:
        raw = dict(result.get("runner_result") or result.get("raw_result") or {})
        runner_code = str(raw.get("error_code") or result.get("error_code") or "")
        normalized_code = runner_code.lower()
        retryable = False
        if runner_code in {"APPTAINER_MISSING", "SIF_MISSING"}:
            error_type = "container_runtime_missing"
        elif normalized_code in _HPC_RUNNER_TIMEOUT_ERROR_CODES:
            error_type = "hpc_runner_timeout"
            retryable = True
        elif normalized_code in _HPC_RUNNER_UNAVAILABLE_ERROR_CODES:
            error_type = "hpc_runner_unavailable"
            retryable = True
        else:
            error_type = (
                "nonzero_exit"
                if result.get("exit_code") not in {None, 0}
                else "hpc_operation_failed"
            )
        if retryable:
            hint = (
                "Retry only after the trusted runner transport recovers; do not "
                "fall back to Host-local or sandbox binaries."
            )
        else:
            hint = (
                "Inspect the safe runner diagnostics and fix the S14 "
                "toolchain/runtime packaging before retrying."
            )
        return PipelineSdkFailure(
            error_type=error_type,
            message=f"{method} HPC runner execution failed.",
            hint=hint,
            stage=str(raw.get("stage") or result.get("stage") or "remote_execution"),
            retryable=retryable,
            sdk_method=method,
            hpc_failure=_hpc_failure_details(
                {
                    "status": result.get("status"),
                    "run_id": result.get("run_id"),
                    "runner_run_id": result.get("runner_run_id"),
                    "execution_mode": result.get("execution_mode"),
                    "exit_code": result.get("exit_code"),
                    "runner_result": raw,
                }
            ),
            details={"runner_error_code": runner_code or None},
        )

    def _run_pipeline_bio_tool(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
        reserved_runner_run_id: str | None = None,
    ) -> dict[str, Any]:
        operation_key = self._pipeline_operation_key(method, params)
        route_policy = self._require_bio_tool_route_policy(method)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        completed = dict(pipeline.get("completed_operations") or {})
        completed_result = dict(completed.get(operation_key) or {})
        if operation_key in completed and not (
            reserved_runner_run_id is not None
            and completed_result.get("status")
            in {
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
            }
        ):
            return completed_result
        placement = self._require_hpc_workspace(
            params.get("placement"), sdk_method=method
        )
        declared_outputs = self._require_declared_outputs(params, sdk_method=method)
        declared_outputs = self._require_canonical_bio_tool_outputs(
            method, declared_outputs
        )
        runner_params = self._bio_tool_runner_params(method=method, params=params)
        stage_refs: list[dict[str, Any]] = []
        artifacts_by_slot: dict[str, SessionArtifactRecord] = {}
        required_artifact_ids: list[str] = []
        tool_inputs: dict[str, Any] = dict(runner_params)
        for slot_name in self._bio_tool_slot_names(method):
            ref = dict(params.get(slot_name) or {})
            stage_refs.append(ref)
            artifact_id = self._require_stage_ref_artifact_id(
                ref,
                placement=placement,
                slot_name=slot_name,
                sdk_method=method,
                session_id=session.session_id,
            )
            artifact = self._require_pipeline_artifact(
                session_id=session.session_id,
                artifact_id=artifact_id,
                sdk_method=method,
            )
            artifacts_by_slot[slot_name] = artifact
            required_artifact_ids.append(artifact_id)
            tool_inputs[f"{slot_name}_artifact_id"] = artifact_id
        self._validate_bio_tool_inputs(
            method=method, artifacts_by_slot=artifacts_by_slot
        )
        adapter_approval_envelope = self._bio_tool_adapter_approval_envelope(
            method=method,
            params=params,
            route_policy=route_policy,
            hpc_workspace_id=str(placement.get("hpc_workspace_id")),
            stage_refs=stage_refs,
            declared_outputs=declared_outputs,
            resource_estimate=self._planned_bio_tool_resource_estimate(method),
        )
        covered_by_approved_plan = self._pipeline_bio_tool_covered_by_approved_plan(
            pipeline=pipeline,
            method=method,
        )
        if (
            operation_key not in set(pipeline.get("approved_operation_keys") or [])
            and not covered_by_approved_plan
        ):
            approval = self._request_pipeline_approval(
                invocation=invocation,
                method=method,
                params=params,
                operation_key=operation_key,
            )
            raise PipelineApprovalRequired(approval)
        if covered_by_approved_plan:
            self._record_pipeline_adapter_approval_envelope(
                invocation=invocation,
                operation_key=operation_key,
                envelope=adapter_approval_envelope,
                approval_source="execution_pipeline_plan",
            )
        tool_inputs.update(
            {
                "route_policy_id": route_policy["route_policy_id"],
                "route_reason": route_policy.get("route_reason"),
                "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
                "toolchain_id": route_policy.get("toolchain_id"),
                "hpc_workspace_id": placement.get("hpc_workspace_id"),
            }
        )
        handoff = ExecutionHandoff(
            execution_goal=f"Run {method} from execution pipeline.",
            required_artifact_ids=tuple(required_artifact_ids),
            catalog_tool_id=method,
            tool_inputs=tool_inputs,
            execution_mode="ssh",
            require_approval=False,
        )
        if covered_by_approved_plan:
            self._consume_approved_plan_operation_call(
                invocation=invocation,
                method=method,
                operation_group="bio_tool_operations",
            )
        result = self._submit_pipeline_hpc_step(
            session=session,
            task=task,
            invocation=invocation,
            handoff=handoff,
            operation_key=operation_key,
            sdk_method=method,
            hpc_workspace_id=str(placement.get("hpc_workspace_id")),
            stage_refs=stage_refs,
            declared_outputs=declared_outputs,
            allow_explicit_fixture_placeholders=False,
            reserved_runner_run_id=reserved_runner_run_id,
        )
        if result.get("status") != RunStatus.SUCCEEDED.value:
            raise self._bio_tool_runner_failure(method=method, result=result)
        run_handle = {
            "kind": "hpc_run_handle",
            "tool_id": result.get("tool_id"),
            "run_id": result.get("run_id"),
            "runner_run_id": result.get("runner_run_id"),
            "status": result.get("status"),
            "execution_mode": result.get("execution_mode"),
            "exit_code": result.get("exit_code"),
            "operation_key": operation_key,
            "placement": "hpc",
            "hpc_workspace_id": placement.get("hpc_workspace_id"),
            "declared_outputs": declared_outputs,
            "stage_refs": stage_refs,
            "route_policy_id": route_policy["route_policy_id"],
            "selected_backend": route_policy.get("selected_backend"),
            "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
            "toolchain_id": route_policy.get("toolchain_id"),
            "summary": f"{method} placement operation succeeded",
            "warnings": [],
        }
        toolchain_runtime_identity = result.get("toolchain_runtime_identity")
        if isinstance(toolchain_runtime_identity, dict):
            run_handle["toolchain_runtime_identity"] = dict(toolchain_runtime_identity)
        parsed_result = result.get("parsed_result")
        if isinstance(parsed_result, dict):
            result_summary = str(parsed_result.get("result_summary") or "")
            if result_summary:
                run_handle["summary"] = result_summary
                run_handle["parsed_result"] = parsed_result
        self._record_pipeline_completed_operation(
            invocation, operation_key, dict(run_handle)
        )
        self._emit(
            "execution.pipeline.step.completed",
            {
                "invocation_id": invocation.invocation_id,
                "operation": method,
                "operation_key": operation_key,
                "run_id": result.get("run_id"),
            },
        )
        return run_handle

    def _run_pipeline_hpc(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        method: str,
        params: dict[str, Any],
        reserved_runner_run_id: str | None = None,
    ) -> dict[str, Any]:
        operation_key = self._pipeline_operation_key(method, params)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        completed = dict(pipeline.get("completed_operations") or {})
        completed_result = dict(completed.get(operation_key) or {})
        if operation_key in completed and not (
            reserved_runner_run_id is not None
            and completed_result.get("status")
            in {
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
            }
        ):
            return completed_result
        placement = self._require_hpc_workspace(
            params.get("placement"), sdk_method=method
        )
        expected_outputs = self._require_declared_outputs(params, sdk_method=method)
        route_policy: dict[str, Any] | None = None
        if method == "structure_tools.fpocket":
            route_policy = self._require_structure_tool_route_policy(method)
            structure_id = self._require_stage_ref_artifact_id(
                params.get("structure"),
                placement=placement,
                slot_name="structure",
                sdk_method=method,
                session_id=session.session_id,
            )
            self._validate_fpocket_artifact(structure_id, sdk_method=method)
        approved = set(
            str(value) for value in list(pipeline.get("approved_operation_keys") or [])
        )
        covered_by_approved_plan = self._pipeline_hpc_covered_by_approved_plan(
            pipeline=pipeline,
            method=method,
            params=params,
        )
        if operation_key not in approved and not covered_by_approved_plan:
            approval = self._request_pipeline_approval(
                invocation=invocation,
                method=method,
                params=params,
                operation_key=operation_key,
            )
            raise PipelineApprovalRequired(approval)
        tool_params = dict(params.get("params") or {})
        if method == "structure_tools.fpocket":
            handoff = ExecutionHandoff(
                execution_goal="Run fpocket from execution pipeline.",
                required_artifact_ids=(structure_id,),
                catalog_tool_id="fpocket",
                tool_inputs={
                    "structure_artifact_id": structure_id,
                    **tool_params,
                    "route_policy_id": route_policy["route_policy_id"],
                    "route_reason": route_policy.get("route_reason"),
                    "runtime_packaging_id": route_policy.get("runtime_packaging_id"),
                    "toolchain_id": route_policy.get("toolchain_id"),
                    "hpc_workspace_id": placement.get("hpc_workspace_id"),
                },
                require_approval=False,
            )
        else:
            receptor_id = self._require_stage_ref_artifact_id(
                params.get("receptor"),
                placement=placement,
                slot_name="receptor",
                sdk_method=method,
                session_id=session.session_id,
            )
            ligand_id = self._require_stage_ref_artifact_id(
                params.get("ligand"),
                placement=placement,
                slot_name="ligand",
                sdk_method=method,
                session_id=session.session_id,
            )
            self._require_pdbqt_artifact(receptor_id, slot_name="vina receptor")
            self._require_pdbqt_artifact(ligand_id, slot_name="vina ligand")
            handoff = ExecutionHandoff(
                execution_goal="Run vina from execution pipeline.",
                required_artifact_ids=(receptor_id, ligand_id),
                catalog_tool_id="vina",
                tool_inputs={
                    "receptor_artifact_id": receptor_id,
                    "ligand_artifact_id": ligand_id,
                    **tool_params,
                },
                require_approval=False,
            )
        stage_refs = [
            value
            for value in (
                params.get("structure"),
                params.get("receptor"),
                params.get("ligand"),
            )
            if isinstance(value, dict)
        ]
        if covered_by_approved_plan:
            self._consume_approved_plan_operation_call(
                invocation=invocation,
                method=method,
                operation_group="hpc_operations",
            )
        result = self._submit_pipeline_hpc_step(
            session=session,
            task=task,
            invocation=invocation,
            handoff=handoff,
            operation_key=operation_key,
            sdk_method=method,
            hpc_workspace_id=str(placement.get("hpc_workspace_id")),
            stage_refs=stage_refs,
            declared_outputs=expected_outputs,
            allow_explicit_fixture_placeholders=True,
            reserved_runner_run_id=reserved_runner_run_id,
        )
        run_handle = {
            "kind": "hpc_run_handle",
            "tool_id": result.get("tool_id"),
            "run_id": result.get("run_id"),
            "runner_run_id": result.get("runner_run_id"),
            "status": result.get("status"),
            "execution_mode": result.get("execution_mode"),
            "exit_code": result.get("exit_code"),
            "error_code": result.get("error_code"),
            "stage": result.get("stage"),
            "raw_result": result.get("raw_result"),
            "runner_result": result.get("runner_result"),
            "operation_key": operation_key,
            "placement": "hpc",
            "hpc_workspace_id": placement.get("hpc_workspace_id"),
            "declared_outputs": expected_outputs,
            "stage_refs": stage_refs,
            "route_policy_id": None
            if route_policy is None
            else route_policy["route_policy_id"],
            "selected_backend": None
            if route_policy is None
            else route_policy.get("selected_backend"),
            "runtime_packaging_id": None
            if route_policy is None
            else route_policy.get("runtime_packaging_id"),
            "toolchain_id": None
            if route_policy is None
            else route_policy.get("toolchain_id"),
            "summary": None,
            "warnings": [],
        }
        toolchain_runtime_identity = result.get("toolchain_runtime_identity")
        if isinstance(toolchain_runtime_identity, dict):
            run_handle["toolchain_runtime_identity"] = dict(toolchain_runtime_identity)
        parsed_result = result.get("parsed_result")
        if isinstance(parsed_result, dict):
            result_summary = str(parsed_result.get("result_summary") or "")
            if result_summary:
                run_handle["summary"] = result_summary
        if run_handle["summary"] is None:
            run_handle["summary"] = (
                f"{method} placement operation {run_handle['status']}"
            )
        completed_payload = dict(run_handle)
        if isinstance(parsed_result, dict):
            completed_payload["parsed_result"] = parsed_result
        self._record_pipeline_completed_operation(
            invocation, operation_key, completed_payload
        )
        if result.get("status") != RunStatus.SUCCEEDED.value:
            self._emit(
                "execution.pipeline.step.failed",
                {
                    "invocation_id": invocation.invocation_id,
                    "operation": method,
                    "operation_key": operation_key,
                    "run_id": result.get("run_id"),
                    "error_code": result.get("error_code"),
                },
            )
            raise self._hpc_operation_runner_failure(method=method, result=result)
        self._emit(
            "execution.pipeline.step.completed",
            {
                "invocation_id": invocation.invocation_id,
                "operation": method,
                "operation_key": operation_key,
                "run_id": result.get("run_id"),
            },
        )
        return run_handle

    def _hpc_operation_runner_failure(
        self,
        *,
        method: str,
        result: dict[str, Any],
    ) -> PipelineSdkFailure:
        raw = dict(result.get("runner_result") or result.get("raw_result") or {})
        runner_code = str(raw.get("error_code") or result.get("error_code") or "")
        normalized_code = runner_code.lower()
        timed_out = normalized_code in _HPC_RUNNER_TIMEOUT_ERROR_CODES
        unavailable = normalized_code in _HPC_RUNNER_UNAVAILABLE_ERROR_CODES
        if timed_out:
            error_type = "hpc_runner_timeout"
        elif unavailable:
            error_type = "hpc_runner_unavailable"
        else:
            error_type = "hpc_operation_failed"
        return PipelineSdkFailure(
            error_type=error_type,
            message=f"{method} Host-supervised HPC execution failed.",
            hint=(
                "Inspect the HPC run and trusted runner diagnostics; do not fall back to Host-local or sandbox binaries."
            ),
            stage=str(raw.get("stage") or result.get("stage") or "remote_execution"),
            retryable=timed_out or unavailable,
            sdk_method=method,
            hpc_failure=_hpc_failure_details(
                {
                    "status": result.get("status"),
                    "run_id": result.get("run_id"),
                    "runner_run_id": result.get("runner_run_id"),
                    "execution_mode": result.get("execution_mode"),
                    "exit_code": result.get("exit_code"),
                    "runner_result": raw,
                }
            ),
            details={"runner_error_code": runner_code or None},
        )

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
        input_ids = {
            str(value)
            for value in list((pipeline.get("inputs") or {}).get("artifact_ids") or [])
        }
        input_ids.update(
            str(value)
            for value in list(
                (pipeline.get("inputs") or {}).get("context_artifact_ids") or []
            )
        )
        requested_artifact_ids = self._pipeline_hpc_artifact_ids(method, params)
        if not requested_artifact_ids.issubset(
            input_ids | set(pipeline.get("preprocess_artifact_ids") or [])
        ):
            return False
        for operation in list(plan.get("hpc_operations") or []):
            if operation.get("method") != method:
                continue
            if int(operation.get("max_calls") or 0) <= 0:
                continue
            planned_ids = {
                str(value) for value in list(operation.get("artifact_ids") or [])
            }
            if planned_ids and not requested_artifact_ids.issubset(
                planned_ids | set(pipeline.get("preprocess_artifact_ids") or [])
            ):
                continue
            return True
        return False

    def _pipeline_hpc_artifact_ids(
        self, method: str, params: dict[str, Any]
    ) -> set[str]:
        placement = dict(params.get("placement") or {})
        if method == "structure_tools.fpocket":
            try:
                return {
                    self._require_stage_ref_artifact_id(
                        params.get("structure"),
                        placement=placement,
                        slot_name="structure",
                        sdk_method=method,
                    )
                }
            except PipelineSdkFailure:
                return set()
        if method == "docking.vina":
            ids: set[str] = set()
            for slot_name in ("receptor", "ligand"):
                try:
                    ids.add(
                        self._require_stage_ref_artifact_id(
                            params.get(slot_name),
                            placement=placement,
                            slot_name=slot_name,
                            sdk_method=method,
                        )
                    )
                except PipelineSdkFailure:
                    return set()
            return ids
        return set()

    def _submit_pipeline_hpc_step(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        handoff: ExecutionHandoff,
        operation_key: str,
        sdk_method: str,
        hpc_workspace_id: str,
        stage_refs: list[dict[str, Any]],
        declared_outputs: list[dict[str, Any]],
        allow_explicit_fixture_placeholders: bool = False,
        reserved_runner_run_id: str | None = None,
    ) -> dict[str, Any]:
        required_artifacts = self._resolve_artifacts(
            session.session_id, handoff.required_artifact_ids
        )
        context_artifacts = self._resolve_artifacts(
            session.session_id, handoff.context_artifact_ids
        )
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
        runtime_identity = dict(pipeline.get("sandbox_runtime_identity") or {})
        metadata.update(
            {
                "pipeline_invocation_id": invocation.invocation_id,
                "sdk_method": sdk_method,
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "pipeline_step_id": operation_key,
                "sandbox_status": "running",
                "hpc_workspace_id": hpc_workspace_id,
                "stage_refs": stage_refs,
                "declared_outputs": declared_outputs,
                "sandbox_runtime_identity_digest": runtime_identity.get(
                    "runtime_identity_digest"
                ),
                "sandbox_image_digest": runtime_identity.get("image_digest"),
                "pipeline_sdk_digest": runtime_identity.get("pipeline_sdk_digest"),
            }
        )
        runspec["metadata"] = metadata
        request = dict(request)
        request["runspec"] = runspec
        self._validate_compiled_runspec_inputs(
            request=request, allowed_artifacts=(*required_artifacts, *context_artifacts)
        )
        existing_run = None
        if reserved_runner_run_id is not None:
            matching_runs = [
                candidate
                for candidate in self.repositories.runs.list_by_session(
                    session.session_id
                )
                if candidate.runner_run_id == reserved_runner_run_id
            ]
            if len(matching_runs) > 1:
                raise PipelineSdkFailure(
                    error_type="durable_runner_identity_conflict",
                    message="The reserved runner identity is bound to multiple Host runs.",
                    hint="Quarantine the conflicting Host records before recovery.",
                    stage="hpc_reconciliation",
                    retryable=False,
                    sdk_method=sdk_method,
                )
            if matching_runs:
                existing_run = matching_runs[0]
                if (
                    existing_run.invocation_id != invocation.invocation_id
                    or existing_run.task_id != invocation.task_id
                    or existing_run.approval_id != invocation.approval_id
                ):
                    raise PipelineSdkFailure(
                        error_type="durable_runner_identity_conflict",
                        message="The reserved runner identity belongs to another Host execution context.",
                        hint="Preserve both records and stop automatic recovery.",
                        stage="hpc_reconciliation",
                        retryable=False,
                        sdk_method=sdk_method,
                    )
        try:
            if reserved_runner_run_id is None:
                outcome = self.runner.submit_execution(session.session_id, request)
            else:
                submit_reserved = getattr(
                    self.runner,
                    "submit_reserved_execution",
                    None,
                )
                if not callable(submit_reserved):
                    raise RuntimeError(
                        "execution runner does not support reserved dispatch"
                    )
                outcome = submit_reserved(
                    session.session_id,
                    request,
                    run_id=reserved_runner_run_id,
                )
                if outcome.run_id != reserved_runner_run_id:
                    raise RuntimeError("reserved runner outcome identity drift")
        except Exception as exc:  # noqa: BLE001 - runner boundary errors must become SDK failures.
            has_projector, runner_failure = _project_runner_staging_failure(exc)
            if runner_failure is not None:
                details = {"runner_failure": runner_failure}
            elif has_projector:
                details = {"reason": _INVALID_RUNNER_STAGING_DIAGNOSTIC_REASON}
            else:
                details = {"reason": _legacy_runner_failure_reason(exc)}
            raise PipelineSdkFailure(
                error_type="hpc_staging_failed",
                message=f"{sdk_method} HPC runner submission or staging failed.",
                hint="Inspect the Host-supervised HPC runner configuration and connectivity; do not fall back to Host-local or sandbox binaries.",
                stage="hpc_staging",
                retryable=True,
                sdk_method=sdk_method,
                details=details,
            ) from exc
        now = utc_now_iso()
        run = (
            RunRecord(
                run_id=f"run_{invocation.invocation_id}_{len(self.repositories.runs.list_by_invocation(session.session_id, invocation.invocation_id)) + 1}",
                session_id=session.session_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                invocation_id=invocation.invocation_id,
                approval_id=invocation.approval_id,
                engine_name=invocation.engine_name,
                runner_run_id=outcome.run_id,
                status=outcome.status,
                execution_mode=outcome.execution_mode,
                remote_run_dir=outcome.remote_run_dir,
                summary=None,
                created_at=now,
                updated_at=now,
                finished_at=now if outcome.status.is_terminal else None,
            )
            if existing_run is None
            else RunRecord(
                run_id=existing_run.run_id,
                session_id=existing_run.session_id,
                task_id=existing_run.task_id,
                lane_id=existing_run.lane_id,
                invocation_id=existing_run.invocation_id,
                approval_id=existing_run.approval_id,
                engine_name=existing_run.engine_name,
                runner_run_id=existing_run.runner_run_id,
                status=outcome.status,
                execution_mode=outcome.execution_mode,
                remote_run_dir=outcome.remote_run_dir,
                summary=existing_run.summary,
                created_at=existing_run.created_at,
                updated_at=now,
                finished_at=now if outcome.status.is_terminal else None,
            )
        )
        self.repositories.runs.save(run)
        final_outcome = outcome
        toolchain_runtime_identity = _project_toolchain_runtime_identity(
            getattr(final_outcome, "toolchain_runtime_identity", None)
            or final_outcome.raw_result.get("toolchain_runtime_identity"),
            execution_mode=final_outcome.execution_mode,
        )
        safe_raw_result = dict(final_outcome.raw_result)
        if toolchain_runtime_identity is None:
            safe_raw_result.pop("toolchain_runtime_identity", None)
        else:
            safe_raw_result["toolchain_runtime_identity"] = dict(
                toolchain_runtime_identity
            )
        explicit_non_cutover_fixture = final_outcome.execution_mode in {
            "fixture_non_cutover",
            "simulation_non_cutover",
        } and bool(safe_raw_result.get("fixture") or safe_raw_result.get("simulation"))
        allow_synthetic_missing = (
            allow_explicit_fixture_placeholders and explicit_non_cutover_fixture
        )
        if final_outcome.status is RunStatus.SUCCEEDED:
            self._save_hpc_pending_outputs(
                session_id=session.session_id,
                invocation=invocation,
                run=run,
                operation_key=operation_key,
                sdk_method=sdk_method,
                hpc_workspace_id=hpc_workspace_id,
                stage_refs=stage_refs,
                declared_outputs=declared_outputs,
                request_metadata=metadata,
                execution_artifacts=final_outcome.artifacts,
                raw_result=safe_raw_result,
                allow_synthetic_missing=allow_synthetic_missing,
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
                artifact_refs=final_outcome.artifacts,
            )
        step_result = {
            "tool_id": handoff.catalog_tool_id,
            "run_id": run.run_id,
            "runner_run_id": run.runner_run_id,
            "status": run.status.value,
            "execution_mode": run.execution_mode,
            "exit_code": final_outcome.exit_code,
            "error_code": safe_raw_result.get("error_code"),
            "stage": safe_raw_result.get("stage"),
            "raw_result": safe_raw_result,
            "parsed_result": None if parsed_result is None else parsed_result.to_dict(),
            "runner_result": {
                "status": safe_raw_result.get("status"),
                "exit_code": safe_raw_result.get("exit_code"),
                "error_code": safe_raw_result.get("error_code"),
                "stage": safe_raw_result.get("stage"),
                "stdout": safe_raw_result.get("stdout"),
                "stderr": safe_raw_result.get("stderr"),
                "logs": safe_raw_result.get("logs"),
                "phase": safe_raw_result.get("phase"),
                "effect_certainty": safe_raw_result.get("effect_certainty"),
                "retry_eligibility": safe_raw_result.get("retry_eligibility"),
                "reconciliation_required": safe_raw_result.get(
                    "reconciliation_required"
                ),
                "retryable": safe_raw_result.get("retryable"),
                "runner_attempt_receipt_digest": safe_raw_result.get(
                    "runner_attempt_receipt_digest"
                ),
            },
        }
        if toolchain_runtime_identity is not None:
            step_result["toolchain_runtime_identity"] = dict(toolchain_runtime_identity)
        return step_result

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
            source_path = (
                Path(tempfile.gettempdir())
                / "openzyme-preprocess"
                / session.session_id
                / invocation.invocation_id
                / f"{title}.smi"
            )
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
                raise ValueError(
                    f"artifact {params.get('artifact_id')!r} is not available in this session"
                )
            if method == "preprocess.prepare_receptor":
                slot_name = "receptor"
                operation = "prepare_receptor"
            elif method == "preprocess.prepare_ligand":
                slot_name = "ligand"
                operation = "prepare_ligand"
            else:
                slot_name = _safe_ref(
                    str(
                        PurePosixPath(artifact.relative_path).stem
                        or artifact.artifact_id
                    )
                )
                operation = "convert_format"
            if operation == "convert_format":
                output_format = str(params.get("output_format") or "pdbqt").lower()
                if output_format != "pdbqt":
                    raise ValueError(
                        "pipeline preprocess.convert_format currently supports output_format='pdbqt'"
                    )
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
        self._append_pipeline_list(
            invocation, "preprocess_artifact_ids", [record.artifact_id]
        )
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
        pending_operation: dict[str, Any] = {
            "operation_key": operation_key,
            "method": method,
            "params": params,
            "approval_id": approval_id,
            "requested_at": now,
        }
        if method in BIO_PROVIDER_ROUTE_POLICY_IDS:
            try:
                route_policy = self._require_bio_route_policy(method)
                output_dir_relative = self._normalize_bio_output_dir(
                    params.get("output_dir"), sdk_method=method
                )
                pending_operation["adapter_approval_envelope"] = (
                    self._bio_adapter_approval_envelope(
                        method=method,
                        params=params,
                        route_policy=route_policy,
                        output_dir_relative=output_dir_relative,
                    )
                )
            except PipelineSdkFailure:
                pass
        if method in BIO_TOOL_ROUTE_POLICY_IDS:
            try:
                route_policy = self._require_bio_tool_route_policy(method)
                placement = self._require_hpc_workspace(
                    params.get("placement"), sdk_method=method
                )
                declared_outputs = self._require_declared_outputs(
                    params, sdk_method=method
                )
                declared_outputs = self._require_canonical_bio_tool_outputs(
                    method, declared_outputs
                )
                stage_refs = self._bio_tool_stage_refs(method=method, params=params)
                pending_operation["adapter_approval_envelope"] = (
                    self._bio_tool_adapter_approval_envelope(
                        method=method,
                        params=params,
                        route_policy=route_policy,
                        hpc_workspace_id=str(placement.get("hpc_workspace_id")),
                        stage_refs=stage_refs,
                        declared_outputs=declared_outputs,
                        resource_estimate=self._planned_bio_tool_resource_estimate(
                            method
                        ),
                    )
                )
            except PipelineSdkFailure:
                pass
        self._update_pipeline_document(
            invocation,
            {
                "pending_operation": pending_operation,
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
                    raise ValueError(
                        "approved execution plan digest does not match the persisted pipeline plan"
                    )
                updates["approved_plan_digest"] = plan.get("plan_digest")
                updates["sandbox_status"] = "approved"
            elif pending.get("operation_key"):
                approved = list(pipeline.get("approved_operation_keys") or [])
                if str(pending["operation_key"]) not in approved:
                    approved.append(str(pending["operation_key"]))
                updates["approved_operation_keys"] = approved
                updates["pending_operation"] = None
                updates["sandbox_status"] = "approved"
        elif (
            approval is not None
            and approval.status is not ApprovalRequestStatus.PENDING
        ):
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
            summary="Pipeline sandbox completed."
            if outcome.status is RunStatus.SUCCEEDED
            else "Pipeline sandbox failed.",
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
        self.repositories.runs.save(sandbox_run)
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        persistable_artifacts = (
            outcome.artifacts if outcome.status is RunStatus.SUCCEEDED else ()
        )
        self._persist_artifacts(
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=sandbox_run.run_id,
            runner_run_id=sandbox_run.runner_run_id,
            created_at=now,
            artifacts=persistable_artifacts,
            request_metadata={
                "pipeline_invocation_id": invocation.invocation_id,
                "code_digest": pipeline.get("code_digest"),
                "source_code_artifact_id": pipeline.get("source_code_artifact_id"),
                "source_code_digest": pipeline.get("source_code_digest"),
                "source_code_version": pipeline.get("source_code_version"),
                "input_artifact_ids": list(
                    (pipeline.get("inputs") or {}).get("artifact_ids") or []
                ),
                "preprocess_artifact_ids": list(
                    pipeline.get("preprocess_artifact_ids") or []
                ),
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
            if isinstance(result, dict)
            and result.get("status") == RunStatus.SUCCEEDED.value
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
        error_stage = None
        error_retryable = False
        error_sdk_method = next(
            (
                method
                for method in (
                    *BIO_TOOL_ROUTE_POLICY_IDS,
                    "structure_tools.fpocket",
                    "docking.vina",
                )
                if method in (failure_excerpt or "")
            ),
            None,
        )
        hpc_failure = None
        if (
            failure_excerpt
            and "PipelineSdkError: " in failure_excerpt
            and "error_code=" in failure_excerpt
        ):
            code_match = re.search(r"error_code=([a-zA-Z0-9_.:-]+)", failure_excerpt)
            stage_match = re.search(r"stage=([a-zA-Z0-9_.:-]+)", failure_excerpt)
            retryable_match = re.search(r"retryable=(True|False)", failure_excerpt)
            if code_match:
                error_type = code_match.group(1)
                error_stage = None if stage_match is None else stage_match.group(1)
                error_retryable = (
                    retryable_match is not None and retryable_match.group(1) == "True"
                )
                error_hint = (
                    "The approved Host-supervised SDK operation failed before completion. "
                    "Inspect the structured SDK error and do not fall back to Host-local or sandbox binaries."
                )
        elif (
            failure_excerpt
            and "PipelineSdkError: " in failure_excerpt
            and " failed with status failed" in failure_excerpt
        ):
            error_type = "hpc_operation_failed"
            error_hint = (
                "The pipeline code reached the approved HPC operation, but the HPC runner returned failed. "
                "Do not retry with equivalent pipeline code; inspect the HPC run or runner configuration."
            )
            for completed_result in dict(
                pipeline.get("completed_operations") or {}
            ).values():
                if isinstance(completed_result, dict):
                    hpc_failure = _hpc_failure_details(completed_result)
                    if hpc_failure is not None:
                        break
            if (
                hpc_failure is not None
                and str(hpc_failure.get("error_code") or "").lower()
                in _HPC_RUNNER_TIMEOUT_ERROR_CODES
            ):
                error_type = "hpc_runner_timeout"
                error_hint = (
                    "The Host-supervised HPC SDK call timed out while waiting on the runner or remote SSH/HPC boundary. "
                    "Treat this as an HPC runner timeout, not a Podman sandbox startup failure."
                )
                error_retryable = True
            elif (
                hpc_failure is not None
                and str(hpc_failure.get("error_code") or "").lower()
                in _HPC_RUNNER_UNAVAILABLE_ERROR_CODES
            ):
                error_type = "hpc_runner_unavailable"
                error_hint = (
                    "The trusted HPC runner transport was unavailable before the SDK call could complete. "
                    "Retry only after runner connectivity recovers; do not use a local fallback."
                )
                error_retryable = True
        error_payload = None
        if outcome.status is not RunStatus.SUCCEEDED:
            error_payload = {
                "type": error_type,
                "stage": error_stage
                if hpc_failure is None
                else hpc_failure.get("stage"),
                "retryable": error_retryable or error_type == "hpc_runner_timeout",
                "message": summary,
                "stderr_excerpt": stderr_excerpt,
                "stdout_excerpt": stdout_excerpt,
                "hint": error_hint,
                "sdk_method": error_sdk_method,
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
                "input_artifact_ids": list(
                    (pipeline.get("inputs") or {}).get("artifact_ids") or []
                ),
                "preprocess_artifact_ids": list(
                    pipeline.get("preprocess_artifact_ids") or []
                ),
                "bio_artifact_ids": list(pipeline.get("bio_artifact_ids") or []),
                "completed_operations": completed_operations,
                "output_artifact_ids": [
                    artifact.artifact_id for artifact in all_artifacts
                ],
                "terminal_summary": summary,
                "parsed_result": None
                if not successful_parsed
                else successful_parsed[-1],
                "error": error_payload,
            },
            "sandbox_outcome": {
                "run_id": outcome.run_id,
                "status": outcome.status.value,
                "execution_mode": outcome.execution_mode,
                "remote_run_dir": outcome.remote_run_dir,
                "exit_code": outcome.exit_code,
                "raw_result": {
                    **outcome.raw_result,
                    **(
                        {"artifacts": {}}
                        if outcome.status is not RunStatus.SUCCEEDED
                        else {}
                    ),
                },
            },
            "runs": [
                run.to_dict()
                for run in self.repositories.runs.list_by_invocation(
                    invocation.session_id, invocation.invocation_id
                )
            ],
            "artifacts": [
                project_artifact_for_agent(artifact) for artifact in all_artifacts
            ],
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
        status = (
            EngineInvocationStatus.SUCCEEDED
            if outcome.status is RunStatus.SUCCEEDED
            else EngineInvocationStatus.FAILED
        )
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
        self._update_pipeline_document(
            invocation, {"sandbox_status": outcome.status.value}
        )
        self._emit(
            "execution.pipeline.completed"
            if outcome.status is RunStatus.SUCCEEDED
            else "execution.pipeline.failed",
            {"invocation_id": invocation.invocation_id, "status": status.value},
        )
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": finalized.invocation_id,
                "engine_name": finalized.engine_name,
                "status": finalized.status.value,
            },
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
        required_artifacts = self._resolve_artifacts(
            session.session_id, handoff.required_artifact_ids
        )
        context_artifacts = self._resolve_artifacts(
            session.session_id, handoff.context_artifact_ids
        )
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
                    "artifact_ids": [
                        artifact.artifact_id for artifact in preprocess_artifacts
                    ],
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
            declared_outputs = [
                dict(item)
                for item in list(pipeline.get("expected_outputs") or [])
                if isinstance(item, dict) and item.get("path")
            ]
            if declared_outputs:
                runspec["expected_outputs"] = declared_outputs
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
            runner_run_id=outcome.run_id,
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
            return self._finalize_terminal(
                invocation=invocation, run=run, handoff=handoff, outcome=outcome
            )
        running = self._replace_invocation(
            invocation, status=EngineInvocationStatus.RUNNING, finished_at=None
        )
        self.repositories.invocations.save(running)
        self._emit(
            "engine.invocation.updated",
            {
                "invocation_id": running.invocation_id,
                "engine_name": running.engine_name,
                "status": "running",
            },
        )
        return ExecutionStartResult(invocation=running, run=run, approval=None)

    def _validate_compiled_runspec_inputs(
        self,
        *,
        request: dict[str, Any],
        allowed_artifacts: tuple[SessionArtifactRecord, ...],
    ) -> None:
        runspec = dict(request.get("runspec") or {})
        allowed_by_id = {
            artifact.artifact_id: artifact for artifact in allowed_artifacts
        }
        allowed_paths = {
            artifact.storage_uri: artifact.artifact_id for artifact in allowed_artifacts
        }
        for item in list(runspec.get("inputs") or []):
            if not isinstance(item, dict):
                raise ValueError("runspec inputs must be objects")
            artifact_id = item.get("artifact_id")
            local_path = str(item.get("local_path") or "")
            if not artifact_id:
                raise ValueError("runspec inputs must include artifact_id")
            artifact = allowed_by_id.get(str(artifact_id))
            if artifact is None:
                raise ValueError(
                    f"runspec input artifact_id {artifact_id!r} is not a resolved session artifact"
                )
            if artifact.storage_uri != local_path:
                expected_id = allowed_paths.get(local_path)
                if expected_id is None:
                    raise ValueError(
                        f"runspec input local_path {local_path!r} is not a resolved session artifact"
                    )
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
        request_runspec = dict(
            (self._require_input_payload(invocation).get("request") or {}).get(
                "runspec"
            )
            or {}
        )
        persistable_artifacts = (
            outcome.artifacts if outcome.status is RunStatus.SUCCEEDED else ()
        )
        artifacts = self._persist_artifacts(
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=run.run_id,
            created_at=now,
            artifacts=persistable_artifacts,
            runner_run_id=run.runner_run_id,
            request_metadata=dict(request_runspec.get("metadata") or {}),
            expected_outputs=tuple(
                dict(item)
                for item in list(request_runspec.get("expected_outputs") or [])
            ),
        )
        parser = self.parser or DefaultExecutionResultParser()
        parsed_result = parser.parse_result(
            handoff=handoff, outcome=outcome, artifact_refs=artifacts
        )
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
                        "exit_code": outcome.exit_code,
                        "artifacts": [
                            artifact.to_dict() for artifact in persistable_artifacts
                        ],
                        "raw_result": {
                            **outcome.raw_result,
                            **(
                                {"artifacts": {}}
                                if outcome.status is not RunStatus.SUCCEEDED
                                else {}
                            ),
                        },
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
            approval=None
            if invocation.approval_id is None
            else self.repositories.approvals.get(invocation.approval_id),
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
        input_artifact_ids = list(
            request_metadata.get("input_artifact_ids")
            or request_metadata.get("required_artifact_ids")
            or []
        )
        preprocess_artifact_ids = list(
            request_metadata.get("preprocess_artifact_ids") or []
        )
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
                    **dict(artifact.metadata or {}),
                    "source": "execution_engine",
                    "runner_run_id": runner_run_id,
                    "remote_path": artifact.relative_path,
                    "expected_output_path": artifact.relative_path,
                    "tool_contract": tool_contract,
                    "pipeline_invocation_id": invocation_id,
                    "code_digest": request_metadata.get("code_digest"),
                    "source_code_artifact_id": request_metadata.get(
                        "source_code_artifact_id"
                    ),
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

    def _prepare_bio_artifact_drafts(
        self,
        *,
        session_id: str,
        output_root: Path,
        output_dir_relative: str,
        drafts: tuple[BioArtifactDraft, ...],
        sdk_method: str,
    ) -> tuple[_PreparedBioArtifactDraft, ...]:
        prepared: list[_PreparedBioArtifactDraft] = []
        seen_paths: set[str] = set()
        for draft in drafts:
            relative = PurePosixPath(draft.relative_path)
            relative_path = relative.as_posix()
            if (
                relative.is_absolute()
                or not relative_path
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise PipelineSdkFailure(
                    error_type="provider_artifactization_failed",
                    message=f"Bio SDK generated invalid artifact path {draft.relative_path!r}.",
                    hint="Retry after fixing the Host bio provider adapter.",
                    stage="bio_artifact_registration",
                    retryable=False,
                    sdk_method=sdk_method,
                )
            workspace_relative_path = PurePosixPath(output_dir_relative) / relative
            public_path = workspace_relative_path.as_posix()
            if public_path in seen_paths:
                raise PipelineSdkFailure(
                    error_type="provider_output_path_invalid",
                    message=f"Bio provider emitted duplicate output path {public_path!r}.",
                    hint="Use one distinct relative path for each provider output.",
                    stage="bio_output_path_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={"relative_path": public_path},
                )
            seen_paths.add(public_path)
            safe_content = _sanitize_provider_content(draft.content)
            content_digest = _sha256_text(safe_content)
            self._reject_bio_output_conflict(
                session_id=session_id,
                relative_path=public_path,
                content_digest=content_digest,
                sdk_method=sdk_method,
            )
            prepared.append(
                _PreparedBioArtifactDraft(
                    draft=draft,
                    storage_path=output_root / relative_path,
                    workspace_relative_path=workspace_relative_path,
                    safe_content=safe_content,
                    content_digest=content_digest,
                )
            )
        return tuple(prepared)

    @staticmethod
    def _preflight_bio_registration_metadata(
        *,
        boundary: ArtifactBoundaryService,
        session_id: str,
        sandbox_workspace_id: str,
        workspace_relative_path: PurePosixPath,
        metadata: dict[str, Any],
        sdk_method: str | None,
    ) -> None:
        try:
            boundary.resolve_registration_metadata(
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                metadata=metadata,
            )
        except ArtifactBoundaryError as exc:
            raise PipelineSdkFailure(
                error_type="provider_artifactization_failed",
                message=f"Bio provider output {workspace_relative_path.as_posix()!r} failed artifact boundary registration.",
                hint=exc.hint
                or "Inspect the provider transcript and retry after fixing the adapter output.",
                stage="bio_artifact_registration",
                retryable=False,
                sdk_method=sdk_method,
                details={"boundary_error_code": exc.error_code, **exc.details},
            ) from exc

    def _persist_bio_artifacts(
        self,
        *,
        session: Any,
        invocation: EngineInvocation,
        output_dir_relative: str,
        operation_key: str,
        drafts: tuple[BioArtifactDraft, ...],
        request_metadata: dict[str, Any],
        run_id: str | None = None,
    ) -> tuple[SessionArtifactRecord, ...]:
        persisted: list[SessionArtifactRecord] = []
        boundary = self._ensure_pipeline_artifact_boundary_workspace(invocation)
        sandbox_workspace_id = self._pipeline_sandbox_workspace_id(invocation)
        workspace_root = (
            self.sandbox_workspace_root
            or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
        )
        output_root = (
            workspace_root / sandbox_workspace_id / "output" / output_dir_relative
        )
        prepared_drafts = self._prepare_bio_artifact_drafts(
            session_id=session.session_id,
            output_root=output_root,
            output_dir_relative=output_dir_relative,
            drafts=drafts,
            sdk_method=str(request_metadata.get("sdk_method") or ""),
        )
        prepared_registrations: list[
            tuple[_PreparedBioArtifactDraft, dict[str, Any]]
        ] = []
        for prepared in prepared_drafts:
            draft = prepared.draft
            metadata = {
                **_sanitize_provider_value(draft.metadata),
                "producer": "host_supervised_bio_provider",
                "pipeline_invocation_id": invocation.invocation_id,
                "sdk_method": request_metadata.get("sdk_method"),
                "provider": request_metadata.get("provider"),
                "provider_request_id": request_metadata.get("provider_request_id"),
                "route_policy_id": request_metadata.get("route_policy_id"),
                "selected_backend": request_metadata.get("selected_backend"),
                "runtime_packaging_id": request_metadata.get("runtime_packaging_id"),
                "provider_config_digest": request_metadata.get(
                    "provider_config_digest"
                ),
                "code_digest": request_metadata.get("code_digest"),
                "source_code_artifact_id": request_metadata.get(
                    "source_code_artifact_id"
                ),
                "source_code_digest": request_metadata.get("source_code_digest"),
                "source_code_version": request_metadata.get("source_code_version"),
                "pipeline_step_id": operation_key,
                "input_artifact_ids": list(
                    request_metadata.get("input_artifact_ids") or []
                ),
                "preprocess_artifact_ids": list(
                    request_metadata.get("preprocess_artifact_ids") or []
                ),
                "output_dir": request_metadata.get("output_dir"),
            }
            self._preflight_bio_registration_metadata(
                boundary=boundary,
                session_id=session.session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                workspace_relative_path=prepared.workspace_relative_path,
                metadata=metadata,
                sdk_method=request_metadata.get("sdk_method"),
            )
            prepared_registrations.append((prepared, metadata))
        for prepared, metadata in prepared_registrations:
            draft = prepared.draft
            prepared.storage_path.parent.mkdir(parents=True, exist_ok=True)
            prepared.storage_path.write_text(prepared.safe_content, encoding="utf-8")
            try:
                result = boundary.register(
                    session_id=session.session_id,
                    sandbox_workspace_id=sandbox_workspace_id,
                    path=f"/workspace/output/{prepared.workspace_relative_path.as_posix()}",
                    kind=draft.kind,
                    format=draft.format,
                    metadata=metadata,
                    validation_profile=(
                        None
                        if metadata.get("validation_profile") in {None, ""}
                        else str(metadata["validation_profile"])
                    ),
                    invocation_id=invocation.invocation_id,
                    run_id=run_id,
                )
            except ArtifactBoundaryError as exc:
                raise PipelineSdkFailure(
                    error_type="provider_artifactization_failed",
                    message=f"Bio provider output {prepared.workspace_relative_path.as_posix()!r} failed artifact boundary registration.",
                    hint=exc.hint
                    or "Inspect the provider transcript and retry after fixing the adapter output.",
                    stage="bio_artifact_registration",
                    retryable=False,
                    sdk_method=request_metadata.get("sdk_method"),
                    details={"boundary_error_code": exc.error_code, **exc.details},
                ) from exc
            record = result.artifact
            self._emit(
                "artifact.recorded",
                {
                    "artifact_id": record.artifact_id,
                    "session_id": record.session_id,
                    "relative_path": record.relative_path,
                    "source": "sandbox_artifact_boundary",
                },
            )
            persisted.append(record)
        return tuple(persisted)

    def _persist_sandbox_bio_artifacts(
        self,
        *,
        operation: ControlledOperation,
        output_dir_relative: str,
        operation_key: str,
        drafts: tuple[BioArtifactDraft, ...],
        request_metadata: dict[str, Any],
    ) -> tuple[SessionArtifactRecord, ...]:
        persisted: list[SessionArtifactRecord] = []
        workspace_root = (
            self.sandbox_workspace_root
            or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
        )
        output_root = (
            workspace_root
            / operation.sandbox_workspace_id
            / "output"
            / output_dir_relative
        )
        boundary = ArtifactBoundaryService(
            self.repositories,
            workspace_root=workspace_root,
            blob_store_root=self.artifact_blob_root,
        )
        prepared_drafts = self._prepare_bio_artifact_drafts(
            session_id=operation.session_id,
            output_root=output_root,
            output_dir_relative=output_dir_relative,
            drafts=drafts,
            sdk_method=str(request_metadata.get("sdk_method") or ""),
        )
        prepared_registrations: list[
            tuple[_PreparedBioArtifactDraft, dict[str, Any]]
        ] = []
        for prepared in prepared_drafts:
            draft = prepared.draft
            metadata = {
                **_sanitize_provider_value(draft.metadata),
                "producer": "host_supervised_bio_provider",
                "controlled_operation_id": operation.operation_id,
                "sandbox_run_id": operation.sandbox_run_id,
                "sandbox_workspace_id": operation.sandbox_workspace_id,
                "sdk_method": request_metadata.get("sdk_method"),
                "provider": request_metadata.get("provider"),
                "provider_request_id": request_metadata.get("provider_request_id"),
                "route_policy_id": request_metadata.get("route_policy_id"),
                "selected_backend": request_metadata.get("selected_backend"),
                "runtime_packaging_id": request_metadata.get("runtime_packaging_id"),
                "provider_config_digest": request_metadata.get(
                    "provider_config_digest"
                ),
                "source_code_artifact_id": request_metadata.get(
                    "source_code_artifact_id"
                ),
                "source_code_digest": request_metadata.get("source_code_digest"),
                "source_code_version": request_metadata.get("source_code_version"),
                "pipeline_step_id": operation_key,
                "input_artifact_ids": list(
                    request_metadata.get("input_artifact_ids") or []
                ),
                "preprocess_artifact_ids": [],
                "output_dir": request_metadata.get("output_dir"),
            }
            self._preflight_bio_registration_metadata(
                boundary=boundary,
                session_id=operation.session_id,
                sandbox_workspace_id=operation.sandbox_workspace_id,
                workspace_relative_path=prepared.workspace_relative_path,
                metadata=metadata,
                sdk_method=request_metadata.get("sdk_method"),
            )
            prepared_registrations.append((prepared, metadata))
        for prepared, metadata in prepared_registrations:
            draft = prepared.draft
            prepared.storage_path.parent.mkdir(parents=True, exist_ok=True)
            prepared.storage_path.write_text(prepared.safe_content, encoding="utf-8")
            try:
                result = boundary.register(
                    session_id=operation.session_id,
                    sandbox_workspace_id=operation.sandbox_workspace_id,
                    path=f"/workspace/output/{prepared.workspace_relative_path.as_posix()}",
                    kind=draft.kind,
                    format=draft.format,
                    metadata=metadata,
                    validation_profile=(
                        None
                        if metadata.get("validation_profile") in {None, ""}
                        else str(metadata["validation_profile"])
                    ),
                    invocation_id=None,
                    run_id=None,
                    source_snapshot_artifact_id=(operation.source_snapshot_artifact_id),
                )
            except ArtifactBoundaryError as exc:
                raise PipelineSdkFailure(
                    error_type="provider_artifactization_failed",
                    message=f"Bio provider output {prepared.workspace_relative_path.as_posix()!r} failed artifact boundary registration.",
                    hint=exc.hint
                    or "Inspect the provider transcript and retry after fixing the adapter output.",
                    stage="bio_artifact_registration",
                    retryable=False,
                    sdk_method=request_metadata.get("sdk_method"),
                    details={"boundary_error_code": exc.error_code, **exc.details},
                ) from exc
            record = result.artifact
            self._emit(
                "artifact.recorded",
                {
                    "artifact_id": record.artifact_id,
                    "session_id": record.session_id,
                    "relative_path": record.relative_path,
                    "source": "sandbox_artifact_boundary",
                },
            )
            persisted.append(record)
        return tuple(persisted)

    def _reject_bio_output_conflict(
        self,
        *,
        session_id: str,
        relative_path: str,
        content_digest: str,
        sdk_method: str,
    ) -> None:
        for artifact in self.repositories.artifacts.list_by_session(session_id):
            if artifact.relative_path != relative_path:
                continue
            existing_digest = str((artifact.metadata or {}).get("content_digest") or "")
            if existing_digest and existing_digest != content_digest:
                raise PipelineSdkFailure(
                    error_type="provider_output_path_invalid",
                    message=f"Bio provider output path {relative_path!r} already exists with a different digest.",
                    hint="Use a fresh output_dir for each provider request.",
                    stage="bio_output_path_validation",
                    retryable=False,
                    sdk_method=sdk_method,
                    details={
                        "relative_path": relative_path,
                        "existing_artifact_id": artifact.artifact_id,
                        "existing_digest": existing_digest,
                        "new_digest": content_digest,
                    },
                )

    def _resolve_artifacts(
        self, session_id: str, artifact_ids: tuple[str, ...]
    ) -> tuple[SessionArtifactRecord, ...]:
        resolved: list[SessionArtifactRecord] = []
        for artifact_id in artifact_ids:
            artifact = self.repositories.artifacts.get(artifact_id)
            if artifact is None:
                raise ValueError(f"artifact {artifact_id!r} does not exist")
            if artifact.session_id != session_id:
                raise ValueError(
                    f"artifact {artifact_id!r} belongs to session {artifact.session_id!r}, not {session_id!r}"
                )
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
        run = self.repositories.runs.get_by_invocation(
            invocation.session_id, invocation.invocation_id
        )
        if run is None:
            raise ValueError(
                f"invocation {invocation.invocation_id!r} does not have a persisted run"
            )
        return run

    def _load_approval(self, invocation: EngineInvocation) -> ApprovalRequest | None:
        return (
            None
            if invocation.approval_id is None
            else self.repositories.approvals.get(invocation.approval_id)
        )

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
            raise ValueError(
                f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}"
            )
        return task

    def _require_invocation(self, invocation_id: str) -> EngineInvocation:
        invocation = self.repositories.invocations.get(invocation_id)
        if invocation is None:
            raise ValueError(f"invocation {invocation_id!r} does not exist")
        return invocation

    def _require_session_invocation(
        self,
        session_id: str,
        invocation_id: str,
    ) -> EngineInvocation:
        invocation = self._require_invocation(invocation_id)
        if invocation.session_id != session_id:
            raise ValueError(
                f"invocation {invocation_id!r} belongs to session "
                f"{invocation.session_id!r}, not {session_id!r}"
            )
        return invocation

    def _require_input_payload(self, invocation: EngineInvocation) -> dict[str, Any]:
        if invocation.input_ref is None:
            raise ValueError(
                f"invocation {invocation.invocation_id!r} does not have an input document"
            )
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

    def _update_pipeline_document(
        self, invocation: EngineInvocation, updates: dict[str, Any]
    ) -> None:
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

    def _append_pipeline_list(
        self, invocation: EngineInvocation, key: str, values: list[str]
    ) -> None:
        pipeline = dict(self._require_input_payload(invocation).get("pipeline") or {})
        current = list(pipeline.get(key) or [])
        for value in values:
            if value not in current:
                current.append(value)
        self._update_pipeline_document(invocation, {key: current})

    def _pipeline_operation_key(self, method: str, params: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"method": method, "params": params}, sort_keys=True, separators=(",", ":")
        )
        return f"{method}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"

    def _require_pdbqt_artifact(self, artifact_id: str, *, slot_name: str) -> None:
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None:
            raise ValueError(f"{slot_name} artifact {artifact_id!r} does not exist")
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        if (
            metadata_format == "pdbqt"
            or artifact.storage_uri.lower().endswith(".pdbqt")
            or artifact.relative_path.lower().endswith(".pdbqt")
        ):
            return
        raise ValueError(
            f"{slot_name} artifact {artifact_id!r} must be PDBQT; use preprocess.prepare_receptor/prepare_ligand first"
        )

    def _validate_fpocket_artifact(
        self, artifact_id: str, *, sdk_method: str = "structure_tools.fpocket"
    ) -> None:
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None:
            raise PipelineSdkFailure(
                error_type="invalid_fpocket_input",
                message=f"fpocket structure artifact {artifact_id!r} does not exist.",
                hint="Stage an existing PDB artifact before calling structure_tools.fpocket.",
                stage="input_validation",
                retryable=False,
                sdk_method=sdk_method,
            )
        metadata_format = str((artifact.metadata or {}).get("format") or "").lower()
        is_pdb = (
            metadata_format == "pdb"
            or artifact.storage_uri.lower().endswith(".pdb")
            or artifact.relative_path.lower().endswith(".pdb")
        )
        if not is_pdb:
            raise PipelineSdkFailure(
                error_type="invalid_fpocket_input",
                message=f"fpocket structure artifact {artifact_id!r} must be a PDB file or declare metadata format=pdb.",
                hint="Use a valid PDB artifact for fpocket; convert or replace non-PDB structures before requesting HPC approval.",
                stage="input_validation",
                retryable=False,
                sdk_method=sdk_method,
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
                sdk_method=sdk_method,
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
            "rcsb_pdb.download_structure": ("rcsb_pdb.download_structure", "bio.md"),
            "bio_tools.cdhit": ("bio_tools.cdhit", "bio-tools.md"),
            "bio_tools.mafft": ("bio_tools.mafft", "bio-tools.md"),
            "bio_tools.hmmbuild": ("bio_tools.hmmbuild", "bio-tools.md"),
            "bio_tools.hmmalign": ("bio_tools.hmmalign", "bio-tools.md"),
            "bio_tools.hmmer_search_cli": (
                "bio_tools.hmmer_search_cli",
                "bio-tools.md",
            ),
            "preprocess.convert_format": ("preprocess.convert_format", None),
            "preprocess.prepare_receptor": ("preprocess.prepare_receptor", None),
            "preprocess.prepare_ligand": ("preprocess.prepare_ligand", None),
            "preprocess.smiles_to_3d": ("preprocess.smiles_to_3d", None),
            "hpc.workspace": ("hpc.workspace", "sdk-overview.md"),
            "structure_tools.fpocket": ("structure_tools.fpocket", "hpc-fpocket.md"),
            "docking.vina": ("docking.vina", "hpc-vina.md"),
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
        supported_operations = {
            "artifacts.get",
            "artifacts.register",
            "artifacts.register_many",
            "bio.ncbi_fetch_proteins",
            "bio.uniprot_fetch",
            "bio.hmmer_search",
            "rcsb_pdb.download_structure",
            "bio_tools.cdhit",
            "bio_tools.mafft",
            "bio_tools.hmmbuild",
            "bio_tools.hmmalign",
            "bio_tools.hmmer_search_cli",
            "preprocess.convert_format",
            "preprocess.prepare_receptor",
            "preprocess.prepare_ligand",
            "preprocess.smiles_to_3d",
            "hpc.workspace",
            "structure_tools.fpocket",
            "docking.vina",
            "run.wait",
            "run.fetch_artifacts",
        }
        operations_by_name: dict[str, dict[str, Any]] = {}

        class OperationBoundVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.multiplier = 1
                self.dynamic_depth = 0

            def _visit_statements(self, statements: list[ast.stmt]) -> None:
                for statement in statements:
                    self.visit(statement)

            def _visit_dynamic(self, nodes: list[ast.AST]) -> None:
                self.dynamic_depth += 1
                try:
                    for nested in nodes:
                        self.visit(nested)
                finally:
                    self.dynamic_depth -= 1

            def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast visitor API
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    operation = f"{func.value.id}.{func.attr}"
                    if operation in supported_operations:
                        keyword, doc_id = doc_hints.get(operation, (operation, None))
                        item = operations_by_name.setdefault(
                            operation,
                            {
                                "operation": operation,
                                "approval_required": operation
                                in {
                                    "bio.ncbi_fetch_proteins",
                                    "bio.uniprot_fetch",
                                    "bio.hmmer_search",
                                    "rcsb_pdb.download_structure",
                                    "structure_tools.fpocket",
                                    "docking.vina",
                                },
                                "doc_keyword": keyword,
                                "max_calls": 0,
                                "dynamic_call_count": 0,
                                "call_sites": [],
                            },
                        )
                        if doc_id is not None:
                            item["doc_id"] = doc_id
                        dynamic = self.dynamic_depth > 0
                        if dynamic:
                            item["dynamic_call_count"] += 1
                        else:
                            item["max_calls"] += self.multiplier
                        item["call_sites"].append(
                            {
                                "line": int(getattr(node, "lineno", 0)),
                                "bounded": not dynamic,
                                "multiplier": None if dynamic else self.multiplier,
                            }
                        )
                self.generic_visit(node)

            def visit_For(self, node: ast.For) -> None:  # noqa: N802 - ast visitor API
                self.visit(node.iter)
                iterations = ExecutionEngine._static_pipeline_loop_iterations(node.iter)
                if iterations is None:
                    self._visit_dynamic([*node.body, *node.orelse])
                    return
                previous_multiplier = self.multiplier
                self.multiplier *= iterations
                try:
                    self._visit_statements(node.body)
                finally:
                    self.multiplier = previous_multiplier
                self._visit_statements(node.orelse)

            def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802 - ast visitor API
                self.visit(node.iter)
                self._visit_dynamic([*node.body, *node.orelse])

            def visit_While(self, node: ast.While) -> None:  # noqa: N802 - ast visitor API
                self._visit_dynamic([node.test, *node.body, *node.orelse])

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast visitor API
                for decorator in node.decorator_list:
                    self.visit(decorator)
                for default in [*node.args.defaults, *node.args.kw_defaults]:
                    if default is not None:
                        self.visit(default)
                self._visit_dynamic(list(node.body))

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802 - ast visitor API
                self.visit_FunctionDef(node)

            def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802 - ast visitor API
                self._visit_dynamic([node.body])

            def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast visitor API
                for decorator in node.decorator_list:
                    self.visit(decorator)
                for base in node.bases:
                    self.visit(base)
                self._visit_dynamic(list(node.body))

            def _visit_comprehension(self, node: ast.AST) -> None:
                self._visit_dynamic(list(ast.iter_child_nodes(node)))

            visit_ListComp = _visit_comprehension
            visit_SetComp = _visit_comprehension
            visit_DictComp = _visit_comprehension
            visit_GeneratorExp = _visit_comprehension

        OperationBoundVisitor().visit(tree)
        operations = [
            item
            for item in operations_by_name.values()
            if int(item["max_calls"]) > 0 or int(item["dynamic_call_count"]) > 0
        ]
        for item in operations:
            item["bounded"] = int(item["dynamic_call_count"]) == 0
        return operations

    @staticmethod
    def _static_pipeline_loop_iterations(iterator: ast.AST) -> int | None:
        if isinstance(iterator, (ast.List, ast.Tuple, ast.Set)):
            return len(iterator.elts)
        if not (
            isinstance(iterator, ast.Call)
            and isinstance(iterator.func, ast.Name)
            and iterator.func.id == "range"
            and not iterator.keywords
            and 1 <= len(iterator.args) <= 3
        ):
            return None
        values: list[int] = []
        for argument in iterator.args:
            if not (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, int)
                and not isinstance(argument.value, bool)
            ):
                return None
            values.append(argument.value)
        try:
            return len(range(*values))
        except ValueError:
            return None

    def _build_execution_plan(
        self,
        *,
        code: str,
        code_digest: str,
        inputs: dict[str, Any],
        source_metadata: dict[str, Any],
        sandbox_runtime_identity: dict[str, str],
    ) -> dict[str, Any]:
        operations = self._dry_run_operation_log(code)
        approval_policy = str(inputs.get("approval_policy") or "").lower()
        single_plan_approval_required = bool(
            inputs.get("require_plan_approval")
        ) or approval_policy in {
            "single_plan",
            "always",
            "required",
        }
        artifact_ids = [str(value) for value in list(inputs.get("artifact_ids") or [])]
        context_artifact_ids = [
            str(value) for value in list(inputs.get("context_artifact_ids") or [])
        ]
        declared_pipeline_outputs = [
            dict(item)
            for item in list(inputs.get("expected_outputs") or [])
            if isinstance(item, dict) and item.get("path")
        ]
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
                "max_calls": int(item.get("max_calls") or 0),
                "bounded": bool(item.get("bounded")),
            }
            for item in operations
            if str(item.get("operation", "")).startswith("preprocess.")
        ]
        bio_operations = [
            {
                "method": str(item["operation"]),
                "provider": self._planned_bio_provider(str(item["operation"])),
                "approval_required": True,
                "route_policy_id": BIO_PROVIDER_ROUTE_POLICY_IDS.get(
                    str(item["operation"])
                ),
                "expected_outputs": self._planned_bio_expected_outputs(
                    str(item["operation"])
                ),
                "quota_estimate": self._scale_plan_estimate(
                    self._planned_bio_quota_estimate(str(item["operation"])),
                    multiplier=int(item.get("max_calls") or 0),
                ),
                "doc_keyword": item.get("doc_keyword"),
                "doc_id": item.get("doc_id"),
                "max_calls": int(item.get("max_calls") or 0),
                "bounded": bool(item.get("bounded")),
            }
            for item in operations
            if str(item.get("operation", "")) in BIO_PROVIDER_ROUTE_POLICY_IDS
        ]
        bio_tool_operations = [
            {
                "method": str(item["operation"]),
                "approval_required": (
                    self._planned_bio_tool_backend(str(item["operation"])) == "hpc"
                    and self._planned_bio_tool_route_status(str(item["operation"]))
                    == "ok"
                ),
                "route_policy_id": BIO_TOOL_ROUTE_POLICY_IDS.get(
                    str(item["operation"])
                ),
                "selected_backend": self._planned_bio_tool_backend(
                    str(item["operation"])
                ),
                "route_status": self._planned_bio_tool_route_status(
                    str(item["operation"])
                ),
                "expected_outputs": self._planned_bio_tool_expected_outputs(
                    str(item["operation"])
                ),
                "resource_estimate": self._scale_plan_estimate(
                    self._planned_bio_tool_resource_estimate(str(item["operation"])),
                    multiplier=int(item.get("max_calls") or 0),
                ),
                "quota_estimate": self._scale_plan_estimate(
                    self._planned_bio_tool_quota_estimate(str(item["operation"])),
                    multiplier=int(item.get("max_calls") or 0),
                ),
                "doc_keyword": item.get("doc_keyword"),
                "doc_id": item.get("doc_id"),
                "max_calls": int(item.get("max_calls") or 0),
                "bounded": bool(item.get("bounded")),
            }
            for item in operations
            if str(item.get("operation", "")).startswith("bio_tools.")
        ]
        hpc_operations: list[dict[str, Any]] = []
        all_input_ids = [*artifact_ids, *context_artifact_ids]
        for item in operations:
            method = str(item.get("operation") or "")
            if method not in {"structure_tools.fpocket", "docking.vina"}:
                continue
            artifact_scope = (
                all_input_ids[:1]
                if method == "structure_tools.fpocket"
                else all_input_ids[:2]
            )
            hpc_operations.append(
                {
                    "method": method,
                    "operation_key": self._planned_pipeline_operation_key(
                        method, artifact_scope
                    ),
                    "artifact_ids": artifact_scope,
                    "params": {
                        "source": "static_dry_run",
                        "runtime_params_must_match_policy": True,
                    },
                    "approval_required": True,
                    "expected_outputs": self._planned_expected_outputs(method),
                    "resource_estimate": self._scale_plan_estimate(
                        self._planned_resource_estimate(method),
                        multiplier=int(item.get("max_calls") or 0),
                    ),
                    "quota_estimate": self._scale_plan_estimate(
                        self._planned_quota_estimate(method),
                        multiplier=int(item.get("max_calls") or 0),
                    ),
                    "doc_keyword": item.get("doc_keyword"),
                    "doc_id": item.get("doc_id"),
                    "max_calls": int(item.get("max_calls") or 0),
                    "bounded": bool(item.get("bounded")),
                }
            )
        if single_plan_approval_required and operations:
            approval_requirements = [
                {
                    "kind": "pipeline_plan",
                    "method": "execution.pipeline.start",
                    "operation_key": f"pipeline_plan:{code_digest[:16]}",
                    "reason": "A single execution plan approval is required by pipeline input policy.",
                    "operation_methods": [
                        str(operation.get("operation")) for operation in operations
                    ],
                    "operation_call_bounds": {
                        str(operation.get("operation")): int(
                            operation.get("max_calls") or 0
                        )
                        for operation in operations
                    },
                }
            ]
        else:
            bio_approval_requirements = [
                {
                    "kind": "provider_operation",
                    "method": operation["method"],
                    "operation_key": f"{operation['method']}:provider_policy",
                    "route_policy_id": operation.get("route_policy_id"),
                    "max_calls": operation.get("max_calls"),
                    "reason": "Bio provider execution is approval-gated by policy.",
                }
                for operation in bio_operations
            ]
            hpc_approval_requirements = [
                {
                    "kind": "hpc_operation",
                    "method": operation["method"],
                    "operation_key": operation["operation_key"],
                    "max_calls": operation.get("max_calls"),
                    "reason": "HPC execution is approval-gated by policy.",
                }
                for operation in hpc_operations
            ]
            bio_tool_approval_requirements = [
                {
                    "kind": "hpc_operation",
                    "method": operation["method"],
                    "operation_key": f"{operation['method']}:hpc_policy",
                    "route_policy_id": operation.get("route_policy_id"),
                    "max_calls": operation.get("max_calls"),
                    "reason": "Bio tool HPC execution is approval-gated by S14 route policy.",
                }
                for operation in bio_tool_operations
                if operation.get("approval_required")
            ]
            approval_requirements = [
                *bio_approval_requirements,
                *bio_tool_approval_requirements,
                *hpc_approval_requirements,
            ]
        plan_without_digest = {
            "code_digest": code_digest,
            **source_metadata,
            "sandbox_runtime_identity": sandbox_runtime_identity,
            "approval_policy": approval_policy or None,
            "artifact_reads": artifact_reads,
            "bio_operations": bio_operations,
            "bio_tool_operations": bio_tool_operations,
            "preprocess_operations": preprocess_operations,
            "hpc_operations": hpc_operations,
            "approval_requirements": approval_requirements,
            "expected_outputs": [
                output
                for operation in [
                    *bio_operations,
                    *bio_tool_operations,
                    *hpc_operations,
                ]
                for output in operation["expected_outputs"]
            ]
            + declared_pipeline_outputs,
            "resource_quota_estimate": {
                "hpc_operation_count": sum(
                    int(operation["max_calls"]) for operation in hpc_operations
                ),
                "hpc_jobs": sum(
                    int(operation["quota_estimate"].get("hpc_jobs") or 0)
                    for operation in hpc_operations
                ),
                "bio_operation_count": sum(
                    int(operation["max_calls"]) for operation in bio_operations
                ),
                "bio_tool_operation_count": sum(
                    int(operation["max_calls"]) for operation in bio_tool_operations
                ),
                "preprocess_operation_count": sum(
                    int(operation["max_calls"]) for operation in preprocess_operations
                ),
                "max_runtime_minutes": sum(
                    int(operation["resource_estimate"]["max_runtime_minutes"])
                    for operation in hpc_operations
                ),
                "provider_requests": sum(
                    int(operation["quota_estimate"]["provider_requests"])
                    for operation in bio_operations
                ),
                "local_tool_invocations": sum(
                    int(operation["quota_estimate"]["local_tool_invocations"])
                    for operation in bio_tool_operations
                ),
            },
            "doc_hints": self._plan_doc_hints(operations),
            "operations": operations,
        }
        digest = hashlib.sha256(
            json.dumps(
                plan_without_digest, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
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
            if (
                not node.args
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
            ):
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
                    forbidden.extend(
                        f"Bio.{alias.name}"
                        for alias in node.names
                        if alias.name == "Entrez"
                    )
        return sorted(set(forbidden))

    def _forbidden_pipeline_process_usage(self, code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        forbidden: list[str] = []
        forbidden_os_calls = {
            "system",
            "popen",
            "spawnv",
            "spawnvp",
            "spawnve",
            "execv",
            "execve",
            "execl",
            "execle",
            "execlp",
            "execlpe",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        forbidden.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    forbidden.append("subprocess")
                elif node.module == "os":
                    forbidden.extend(
                        f"os.{alias.name}"
                        for alias in node.names
                        if alias.name in forbidden_os_calls
                    )
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if (
                    isinstance(owner, ast.Name)
                    and owner.id == "os"
                    and node.func.attr in forbidden_os_calls
                ):
                    forbidden.append(f"os.{node.func.attr}")
        return sorted(set(forbidden))

    def _pipeline_bio_call_errors(self, code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        errors: list[str] = []
        bio_operations = {
            "ncbi_fetch_proteins": "bio.ncbi_fetch_proteins",
            "uniprot_fetch": "bio.uniprot_fetch",
            "hmmer_search": "bio.hmmer_search",
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            owner = func.value
            if (
                not isinstance(owner, ast.Name)
                or owner.id != "bio"
                or func.attr not in bio_operations
            ):
                continue
            operation = bio_operations[func.attr]
            output_keyword = next(
                (keyword for keyword in node.keywords if keyword.arg == "output_dir"),
                None,
            )
            if output_keyword is None:
                errors.append(f"{operation} missing output_dir")
                continue
            if isinstance(output_keyword.value, ast.Constant) and isinstance(
                output_keyword.value.value, str
            ):
                try:
                    self._normalize_bio_output_dir(
                        output_keyword.value.value, sdk_method=operation
                    )
                except PipelineSdkFailure as exc:
                    errors.append(f"{operation} invalid output_dir: {exc.message}")
        return errors

    def _planned_pipeline_operation_key(
        self, method: str, artifact_ids: list[str]
    ) -> str:
        canonical = json.dumps(
            {"method": method, "artifact_ids": artifact_ids},
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"{method}:plan:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"

    def _planned_expected_outputs(self, method: str) -> list[dict[str, Any]]:
        if method == "structure_tools.fpocket":
            return [
                {"path": "fpocket.log", "kind": "log"},
                {"path": "pockets/pockets.json", "kind": "result"},
            ]
        if method == "docking.vina":
            return [
                {"path": "vina.log", "kind": "log"},
                {"path": "poses/vina_out.pdbqt", "kind": "structure"},
            ]
        return []

    def _planned_bio_provider(self, method: str) -> str:
        return {
            "bio.ncbi_fetch_proteins": "ncbi",
            "bio.uniprot_fetch": "uniprot",
            "bio.hmmer_search": "ebi_hmmer",
            "rcsb_pdb.download_structure": "rcsb_pdb",
        }.get(method, "unknown")

    def _planned_bio_expected_outputs(self, method: str) -> list[dict[str, Any]]:
        transcript_outputs = [
            {
                "path": "<output_dir>/provider_request.json",
                "kind": "result",
                "format": "json",
            },
            {
                "path": "<output_dir>/provider_observation.json",
                "kind": "result",
                "format": "json",
            },
        ]
        if method == "bio.ncbi_fetch_proteins":
            return [
                *transcript_outputs,
                {
                    "path": "<output_dir>/provider_raw/ncbi_efetch.response.json",
                    "kind": "result",
                    "format": "json",
                },
                {
                    "path": "<output_dir>/provider_parsed/proteins.fasta",
                    "kind": "sequence",
                    "format": "fasta",
                },
                {
                    "path": "<output_dir>/provider_parsed/proteins.metadata.json",
                    "kind": "result",
                    "format": "json",
                },
            ]
        if method == "bio.uniprot_fetch":
            return [
                *transcript_outputs,
                {
                    "path": "<output_dir>/provider_raw/pages.json",
                    "kind": "result",
                    "format": "json",
                },
                {
                    "path": "<output_dir>/provider_parsed/sequences.fasta",
                    "kind": "sequence",
                    "format": "fasta",
                    "optional": True,
                },
                {
                    "path": "<output_dir>/provider_parsed/metadata.json",
                    "kind": "result",
                    "format": "json",
                },
            ]
        if method == "bio.hmmer_search":
            return [
                *transcript_outputs,
                {
                    "path": "<output_dir>/provider_raw/raw_hits.json",
                    "kind": "result",
                    "format": "json",
                },
                {
                    "path": "<output_dir>/provider_parsed/parsed_hits.csv",
                    "kind": "result",
                    "format": "csv",
                },
            ]
        if method == "rcsb_pdb.download_structure":
            return [
                *transcript_outputs,
                {
                    "path": "<output_dir>/provider_parsed/<pdb_id>.<format>",
                    "kind": "structure",
                    "format": "pdb",
                },
            ]
        return []

    def _planned_bio_quota_estimate(self, method: str) -> dict[str, Any]:
        return {"provider_requests": 1, "operation": method, "pagination_pages": 1}

    def _planned_bio_tool_expected_outputs(self, method: str) -> list[dict[str, Any]]:
        return {
            "bio_tools.cdhit": [
                {
                    "path": "bio_tools/cdhit/clustered.fasta",
                    "kind": "sequence",
                    "format": "fasta",
                },
                {
                    "path": "bio_tools/cdhit/clusters.csv",
                    "kind": "result",
                    "format": "csv",
                },
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
            "bio_tools.hmmer_search_cli": [],
        }.get(method, [])

    def _planned_bio_tool_backend(self, method: str) -> str:
        route_policy_id = BIO_TOOL_ROUTE_POLICY_IDS.get(method)
        policy = dict(S12_ROUTE_POLICIES.get(str(route_policy_id)) or {})
        return str(policy.get("selected_backend") or "unknown")

    def _planned_bio_tool_route_status(self, method: str) -> str:
        route_policy_id = BIO_TOOL_ROUTE_POLICY_IDS.get(method)
        policy = dict(S12_ROUTE_POLICIES.get(str(route_policy_id)) or {})
        return str(policy.get("status") or "missing")

    def _planned_bio_tool_quota_estimate(self, method: str) -> dict[str, Any]:
        if method == "bio_tools.hmmer_search_cli":
            return {
                "local_tool_invocations": 0,
                "operation": method,
                "disabled_reason": "unsupported_in_s14",
            }
        return {"local_tool_invocations": 1, "operation": method}

    def _planned_bio_tool_resource_estimate(self, method: str) -> dict[str, Any]:
        if method == "bio_tools.hmmer_search_cli":
            return {
                "cpu": 0,
                "memory_gb": 0,
                "max_runtime_minutes": 0,
                "disabled_reason": "unsupported_in_s14",
            }
        if method == "bio_tools.mafft":
            return {"cpu": 4, "memory_gb": 8, "max_runtime_minutes": 60}
        return {"cpu": 2, "memory_gb": 4, "max_runtime_minutes": 30}

    def _planned_resource_estimate(self, method: str) -> dict[str, Any]:
        if method == "docking.vina":
            return {"cpu": 4, "memory_gb": 8, "max_runtime_minutes": 120}
        return {"cpu": 2, "memory_gb": 4, "max_runtime_minutes": 60}

    def _planned_quota_estimate(self, method: str) -> dict[str, Any]:
        return {"hpc_jobs": 1, "operation": method}

    def _scale_plan_estimate(
        self,
        estimate: dict[str, Any],
        *,
        multiplier: int,
    ) -> dict[str, Any]:
        scaled = dict(estimate)
        for key in {
            "max_runtime_minutes",
            "provider_requests",
            "pagination_pages",
            "local_tool_invocations",
            "hpc_jobs",
        }:
            value = scaled.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                scaled[key] = value * multiplier
        scaled["max_calls"] = multiplier
        return scaled

    def _plan_doc_hints(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        hints: list[dict[str, Any]] = []
        seen: set[tuple[str | None, str | None]] = set()
        for operation in operations:
            key = (
                None
                if operation.get("doc_keyword") is None
                else str(operation.get("doc_keyword")),
                None
                if operation.get("doc_id") is None
                else str(operation.get("doc_id")),
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
        unbounded_operations = [
            operation
            for operation in list(execution_plan.get("operations") or [])
            if not bool(operation.get("bounded"))
        ]
        if unbounded_operations:
            methods = [
                str(operation.get("operation")) for operation in unbounded_operations
            ]
            return {
                "type": "execution_plan_unbounded_calls",
                "stage": "pipeline_static_policy",
                "retryable": False,
                "message": "Pipeline external SDK calls must have a finite static call bound.",
                "hint": (
                    "Inline external SDK calls into top-level code or literal bounded for loops; "
                    f"dynamic calls were found in: {methods}"
                ),
                "sdk_method": methods[0] if methods else None,
            }
        for operation in list(execution_plan.get("hpc_operations") or []):
            if operation.get("method") != "structure_tools.fpocket":
                continue
            artifact_ids = [
                str(value) for value in list(operation.get("artifact_ids") or [])
            ]
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
        return (
            f"{task_id}:execution.pipeline:{phase}:{code_digest[:12]}:{inputs_digest}"
        )

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
        existing_invocation = self._find_invocation_by_idempotency_key(
            session_id=session_id,
            idempotency_key=resolved_idempotency_key,
        )
        if existing_invocation is not None:
            existing_payload: dict[str, Any] = {}
            if existing_invocation.output_ref is not None:
                existing_output = self.repositories.engine_documents.get(
                    existing_invocation.output_ref
                )
                if existing_output is not None:
                    existing_payload = dict(
                        existing_output.payload.get("pipeline") or {}
                    )
            return ExecutionStartResult(
                invocation=existing_invocation,
                run=None,
                approval=None,
                parsed_result=ExecutionParsedResult(
                    result_summary=str(
                        dict(existing_payload.get("error") or {}).get("message")
                        or message
                    ),
                    structured_findings=existing_payload,
                ),
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
                payload={
                    "task_id": task_id,
                    "lane_id": effective_lane_id,
                    "pipeline": payload["pipeline"],
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
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )
        return ExecutionStartResult(
            invocation=invocation,
            run=None,
            approval=None,
            parsed_result=ExecutionParsedResult(
                result_summary=message, structured_findings=payload["pipeline"]
            ),
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
                    "source_code_artifact_id": pipeline_metadata.get(
                        "source_code_artifact_id"
                    ),
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
                    "source_code_artifact_id": pipeline_metadata.get(
                        "source_code_artifact_id"
                    ),
                    "source_code_digest": pipeline_metadata.get("source_code_digest"),
                    "source_code_version": pipeline_metadata.get("source_code_version"),
                    "plan": pipeline_metadata["execution_plan"],
                },
            ),
        )


def _execution_pipeline_start_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="execution.pipeline.start",
        description=(
            "Migration compatibility bridge for starting a Host-supervised execution pipeline "
            "from a previously created pipeline source artifact. Prefer sandbox-first authoring; "
            "this tool must not use Host paths, runner paths, direct SSH, or inline provider credentials."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "lane_id": {"type": "string"},
                "code_artifact_id": {"type": "string"},
                "inputs": {
                    "type": "object",
                    "properties": {
                        "artifact_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "context_artifact_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "additionalProperties": True,
                },
                "dry_run": {"type": "boolean"},
                "invocation_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["task_id", "code_artifact_id"],
            "additionalProperties": False,
        },
    )


def _execution_pipeline_status_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="execution.pipeline.status",
        description="Read status for an existing Host-supervised execution pipeline invocation.",
        input_schema={
            "type": "object",
            "properties": {
                "invocation_id": {"type": "string"},
            },
            "required": ["invocation_id"],
            "additionalProperties": False,
        },
    )


@dataclass(frozen=True, slots=True)
class ExecutionPipelineStartRuntime:
    engine: ExecutionEngine
    tool_name: str = "execution.pipeline.start"

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return _execution_pipeline_start_spec()

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=("executor",),
            supports_parallel=False,
            side_effect=ToolSideEffect.APPROVAL,
            approval_required=True,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=_execution_pipeline_start_spec().input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        session_id = runtime_context.snapshot.session.session_id
        task_id = str(invocation.arguments["task_id"])
        existing_task_invocation = next(
            (
                candidate
                for candidate in runtime_context.repositories.invocations.list_by_task(
                    session_id, task_id
                )
                if candidate.engine_name == self.engine.descriptor.engine_name
                and candidate.status
                not in {EngineInvocationStatus.FAILED, EngineInvocationStatus.CANCELLED}
                and not self.engine._is_pipeline_dry_run_invocation(candidate)
            ),
            None,
        )
        if existing_task_invocation is not None:
            requested_invocation_id = str(
                invocation.arguments.get("invocation_id") or ""
            ).strip()
            requested_idempotency_key = str(
                invocation.arguments.get("idempotency_key") or ""
            ).strip()
            exact_replay = bool(
                (requested_invocation_id or requested_idempotency_key)
                and (
                    not requested_invocation_id
                    or requested_invocation_id
                    == existing_task_invocation.invocation_id
                )
                and (
                    not requested_idempotency_key
                    or requested_idempotency_key
                    == existing_task_invocation.idempotency_key
                )
            )
            input_document = (
                None
                if existing_task_invocation.input_ref is None
                else runtime_context.repositories.engine_documents.get(
                    existing_task_invocation.input_ref
                )
            )
            persisted_pipeline = (
                None
                if input_document is None
                else input_document.payload.get("pipeline")
            )
            requested_lane_id = (
                invocation.lane_id
                if invocation.arguments.get("lane_id") is None
                else str(invocation.arguments["lane_id"])
            )
            request_matches = bool(
                isinstance(persisted_pipeline, dict)
                and str(
                    persisted_pipeline.get("source_code_artifact_id") or ""
                )
                == str(invocation.arguments["code_artifact_id"])
                and dict(persisted_pipeline.get("inputs") or {})
                == dict(invocation.arguments.get("inputs") or {})
                and bool(persisted_pipeline.get("dry_run"))
                == bool(invocation.arguments.get("dry_run", False))
                and existing_task_invocation.lane_id == requested_lane_id
            )
            if exact_replay and request_matches:
                payload = existing_task_invocation.to_dict()
                waiting_for_approval = (
                    existing_task_invocation.status
                    is EngineInvocationStatus.WAITING_APPROVAL
                )
                return ToolResult(
                    call_id=invocation.call_id,
                    tool_name=invocation.tool_name,
                    ok=True,
                    content=json.dumps(payload, sort_keys=True),
                    task_id=existing_task_invocation.task_id,
                    lane_id=existing_task_invocation.lane_id,
                    status="execution_invocation_already_satisfied",
                    summary=(
                        "The exact execution pipeline invocation identity "
                        "already exists; no second pipeline was started."
                    ),
                    details={
                        "invocation_id": (
                            existing_task_invocation.invocation_id
                        ),
                        "invocation_status": (
                            existing_task_invocation.status.value
                        ),
                        "already_satisfied": True,
                        "approval_id": existing_task_invocation.approval_id,
                    },
                    terminal_action=(
                        "runtime_suspended" if waiting_for_approval else None
                    ),
                    terminates_turn=waiting_for_approval,
                )
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
                    "requested_identity_matched": exact_replay,
                    "requested_payload_matched": request_matches,
                },
            )
        result = self.engine.start_pipeline(
            session_id=session_id,
            task_id=task_id,
            code_artifact_id=None
            if invocation.arguments.get("code_artifact_id") is None
            else str(invocation.arguments["code_artifact_id"]),
            code=None
            if invocation.arguments.get("code") is None
            else str(invocation.arguments["code"]),
            inputs=None
            if invocation.arguments.get("inputs") is None
            else dict(invocation.arguments["inputs"]),
            dry_run=bool(invocation.arguments.get("dry_run", False)),
            invocation_id=None
            if invocation.arguments.get("invocation_id") is None
            else str(invocation.arguments["invocation_id"]),
            lane_id=invocation.lane_id
            if invocation.arguments.get("lane_id") is None
            else str(invocation.arguments["lane_id"]),
            idempotency_key=None
            if invocation.arguments.get("idempotency_key") is None
            else str(invocation.arguments["idempotency_key"]),
        )
        waiting_for_approval = (
            result.invocation.status is EngineInvocationStatus.WAITING_APPROVAL
        )
        start_succeeded = result.invocation.status not in {
            EngineInvocationStatus.FAILED,
            EngineInvocationStatus.CANCELLED,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=start_succeeded,
            content=json.dumps(result.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
            status=(
                "execution_pipeline_waiting_approval"
                if waiting_for_approval
                else (
                    "execution_pipeline_started"
                    if start_succeeded
                    else "execution_pipeline_start_failed"
                )
            ),
            summary=(
                "Execution pipeline is durably waiting for approval."
                if waiting_for_approval
                else (
                    "Execution pipeline start was recorded."
                    if start_succeeded
                    else "Execution pipeline start failed."
                )
            ),
            details={
                "invocation_id": result.invocation.invocation_id,
                "invocation_status": result.invocation.status.value,
                "approval_id": (
                    None
                    if result.approval is None
                    else result.approval.approval_id
                ),
            },
            terminal_action=(
                "runtime_suspended" if waiting_for_approval else None
            ),
            terminates_turn=waiting_for_approval,
        )


@dataclass(frozen=True, slots=True)
class ExecutionPipelineStatusRuntime:
    engine: ExecutionEngine
    tool_name: str = "execution.pipeline.status"

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return _execution_pipeline_status_spec()

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=("executor",),
            supports_parallel=True,
            side_effect=ToolSideEffect.READ,
            approval_required=False,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=_execution_pipeline_status_spec().input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        status = self.engine.get_pipeline_status(
            session_id=runtime_context.snapshot.session.session_id,
            invocation_id=str(invocation.arguments["invocation_id"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(status, sort_keys=True),
            task_id=(
                None
                if status.get("task_id") is None
                else str(status["task_id"])
            ),
            lane_id=(
                None
                if status.get("lane_id") is None
                else str(status["lane_id"])
            ),
            status="execution_pipeline_status_projected",
            summary=(
                "Projected execution pipeline invocation "
                f"{status.get('invocation_id')}."
            ),
            details=status,
        )


def register_execution_tools(
    registry: ToolRegistryProtocol, engine: ExecutionEngine
) -> None:
    registry.register_runtime(ExecutionPipelineStartRuntime(engine))
    registry.register_runtime(ExecutionPipelineStatusRuntime(engine))


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
