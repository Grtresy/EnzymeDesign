from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
import zlib

from openzyme_core.workflow_knowledge import workflow_manifest_content_sha256
from openzyme_pipeline import aox_finalization
from openzyme_pipeline import aox_reference
from openzyme_research import safe_public_locator
from openzyme_runtime import LIVE_MICU_TOKEN_HARD_LIMIT
from openzyme_runtime import summarize_live_micu_token_ledger

from .aox_architecture_qualification import AoxArchitectureQualificationError
from .aox_architecture_qualification import (
    normalize_architecture_qualification_receipt,
)
from .aox_cutover_runtime_config import AoxRuntimeConfigSchemaError
from .aox_cutover_runtime_config import AOX_BLANK_WORLD_RUNTIME_CONFIG_V3_SCHEMA_ID
from .aox_cutover_runtime_config import normalize_aox_blank_world_runtime_config
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import DIAGNOSTIC_RUN_POLICY


ATTEMPT_BUNDLE_SCHEMA_ID_V2 = "aox_blank_world_attempt_bundle@2"
ATTEMPT_BUNDLE_SCHEMA_ID_V3 = "aox_blank_world_attempt_bundle@3"
# Backward-compatible public name.  Existing collectors and golden fixtures are
# deliberately frozen on @2; new production campaigns dispatch to @3 explicitly.
ATTEMPT_BUNDLE_SCHEMA_ID = ATTEMPT_BUNDLE_SCHEMA_ID_V2
CAMPAIGN_DECISION_SCHEMA_ID = "aox_blank_world_campaign_decision@1"
DIAGNOSTIC_ROOT_MARKER_SCHEMA_ID = "aox_diagnostic_root_marker@1"
DIAGNOSTIC_ROOT_MARKER_FILENAME = ".aox-diagnostic-root.json"
DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID = "aox_diagnostic_root_proof@1"
BLANK_WORLD_ROOT_PROOF_SCHEMA_ID = "aox_blank_world_root_proof@3"
_LEGACY_BLANK_WORLD_ROOT_PROOF_SCHEMA_ID = "aox_blank_world_root_proof@2"
AOX_LAUNCH_RECEIPT_SCHEMA_ID = "aox_blank_world_launch_receipt@2"
SEALED_SOURCE_TREE_SCHEMA_ID = "openzyme_sealed_source_tree@1"
FORMAL_DELEGATION_REQUEST_SCHEMA_ID = "aox_formal_delegation_request@1"
TYPED_EMPTY_ARTIFACT_VALIDATION_SCHEMA_ID = "openzyme_typed_empty_artifact_validation@1"
KNOWN_POSITIVE_PROBE_SCHEMA_ID = "aox_known_positive_probe@2"
KNOWN_POSITIVE_PROBE_ID = "independent_globin_provider_hpc_probe"
KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS = ("NP_000509.1", "NP_000549.1")
KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS = ("P68871", "P69905")
FAULT_ARTIFACT_BYTE_FLIP_ID = "derived_required_artifact_blob_byte_flip@2"
_FAULT_ALLOWED_PREFAULT_DELIVERABLES = frozenset(
    {
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
    }
)
AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID = "aox_fixed_deliverable_artifact_contract@1"
AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS = {
    "aox_hmm/AOX_ref21.fasta": ("sequence", "fasta"),
    "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta": ("sequence", "fasta"),
    "aox_hmm/AOX_scoring_input.fasta": ("sequence", "fasta"),
    "aox_hmm/target.fasta": ("sequence", "fasta"),
    "aox_hmm/AOX_ref.hmm": ("result", "hmm"),
    "aox_hmm/hits_raw.csv": ("result", "csv"),
    "aox_hmm/hmmer_score_filtered_accessions.csv": ("result", "csv"),
    "aox_hmm/hits_len650_700_200.csv": ("result", "csv"),
    "aox_hmm/AOX_scoring_alignment.fasta": ("sequence", "fasta"),
    "aox_hmm/scored_ref_plus_hits.csv": ("result", "csv"),
    "aox_hmm/AOX_candidates.fasta": ("sequence", "fasta"),
    "aox_hmm/AOX_candidates_cdhit85.fasta": ("sequence", "fasta"),
    "aox_hmm/AOX_candidates_cdhit85.clusters.csv": ("result", "csv"),
    "aox_hmm/nodes.csv": ("result", "csv"),
    "aox_hmm/edges_similarity.csv": ("result", "csv"),
    "aox_hmm/similarity_graph_manifest.json": ("result", "json"),
    "aox_hmm/execution_summary.json": ("result", "json"),
}
_AOX_FIXED_DELIVERABLES = frozenset(AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTEMPT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_EMPTY_RESULT_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_DERIVATION_CONTRACT_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*@[1-9][0-9]*$")
_DELEGATION_REQUEST_PROJECTION_KEYS = {
    "schema_id",
    "document_id",
    "document_kind",
    "task_id",
    "instructions_digest",
    "role",
    "agent_id",
    "nickname",
    "display_name",
    "handle",
    "workflow_refs",
    "workflow_manifests",
}
_TYPED_EMPTY_ARTIFACT_VALIDATION_KEYS = {
    "schema_id",
    "kind",
    "format",
    "validation_profile",
    "empty_result_reason",
    "derivation_contract_id",
    "catalog_validation_digest",
}
_PUBLIC_API_RECEIPT_KEYS = {
    "sequence",
    "method",
    "route",
    "status_code",
    "request_digest",
    "response_digest",
    "response_semantic_digest",
}
_PUBLIC_RESPONSE_BINDING_KEYS = {
    "receipt_sequence",
    "route",
    "response_digest",
    "response_semantic_digest",
}
_EVENT_RESPONSE_BINDING_KEYS = {
    *_PUBLIC_RESPONSE_BINDING_KEYS,
    "event_records",
    "event_records_digest",
}
_BROWSER_APPROVAL_RECEIPT_KEYS = {
    "schema_id",
    "approval_mode",
    "ui_channel",
    "host_process_id",
    "session_id",
    "approval_id",
    "operation_id",
    "operation_digest",
    "sandbox_workspace_id",
    "sandbox_run_id",
    "page_url",
    "served_ui_dist_digest",
    "observation_challenge",
    "pre_workspace_snapshot",
    "pre_workspace_digest",
    "pre_workspace_response_binding",
    "pre_event_cursor",
    "resolution_event_id",
    "resolution_event_cursor",
    "resolution_actor_ref",
    "resolution_command_id",
    "resolution_event_record",
    "continuation_event_id",
    "continuation_event_cursor",
    "continuation_id",
    "continuation_event_record",
    "event_response_bindings",
    "post_workspace_snapshot",
    "post_workspace_digest",
    "post_workspace_response_binding",
    "post_operation_status",
    "driver_resolve_route_absent",
}
_BROWSER_DURABLE_EVENT_KEYS = {
    "schema_id",
    "cursor",
    "event_id",
    "session_id",
    "event_type",
    "schema_version",
    "visibility",
    "actor_ref",
    "command_id",
    "created_at",
    "payload",
    "payload_digest",
}
_BROWSER_OBSERVATION_RECEIPT_KEYS = {
    "schema_id",
    "observation_mode",
    "observation_challenge",
    "session_id",
    "approval_id",
    "operation_id",
    "page_url",
    "host_process_id",
    "served_ui_dist_digest",
    "page_target_id",
    "observation_window_seconds",
    "console_entries",
    "console_entries_digest",
    "application_error_count",
    "page_state",
    "page_state_digest",
    "devtools_command_receipt",
    "devtools_transcript",
    "devtools_transcript_digest",
    "screenshot_png_base64",
    "screenshot_digest",
    "screenshot_width",
    "screenshot_height",
    "host_observation_hold_seconds",
    "host_observation_hold_satisfied",
    "host_observation_submission_timeout_seconds",
    "host_observation_ready_at_unix_ns",
    "host_observation_not_before_unix_ns",
    "host_observation_accepted_at_unix_ns",
}
_BROWSER_PAGE_STATE_KEYS = {
    "session_id",
    "approval_id",
    "operation_id",
    "operation_digest",
    "approval_present",
    "operation_status",
    "final_master_response_id",
    "report_id",
    "report_status",
    "scientific_evidence_digest",
    "workspace_digest",
    "workspace_response_binding",
    "event_stream_digest",
    "event_last_cursor",
    "event_response_binding",
}


def _validated_browser_png(encoded: object) -> tuple[bytes, int, int] | None:
    if not isinstance(encoded, str) or not encoded or len(encoded) > 64 * 1024 * 1024:
        return None
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None
    if len(content) < 45 or content[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    offset = 8
    ihdr: bytes | None = None
    idat_parts: list[bytes] = []
    seen_iend = False
    seen_non_idat_after_idat = False
    while offset < len(content):
        if offset + 12 > len(content):
            return None
        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(content):
            return None
        data = content[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(content[offset + 8 + length : chunk_end], "big")
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            return None
        if chunk_type == b"IHDR":
            if ihdr is not None or offset != 8 or length != 13:
                return None
            ihdr = data
        elif chunk_type == b"IDAT":
            if ihdr is None or seen_iend or seen_non_idat_after_idat:
                return None
            idat_parts.append(data)
        elif chunk_type == b"IEND":
            if ihdr is None or not idat_parts or seen_iend or length != 0:
                return None
            seen_iend = True
            if chunk_end != len(content):
                return None
        elif idat_parts:
            seen_non_idat_after_idat = True
        offset = chunk_end
    if ihdr is None or not idat_parts or not seen_iend:
        return None
    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    bit_depth, color_type, compression, filter_method, interlace = ihdr[8:13]
    channels_by_color_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if (
        width <= 0
        or height <= 0
        or width > 16_384
        or height > 16_384
        or color_type not in channels_by_color_type
        or bit_depth not in valid_depths[color_type]
        or compression != 0
        or filter_method != 0
        or interlace != 0
    ):
        return None
    row_bytes = (width * channels_by_color_type[color_type] * bit_depth + 7) // 8
    expected_decoded_size = height * (1 + row_bytes)
    if expected_decoded_size > 64 * 1024 * 1024:
        return None
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(
            b"".join(idat_parts), expected_decoded_size + 1
        )
    except zlib.error:
        return None
    if (
        len(pixels) != expected_decoded_size
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or any(
            pixels[row * (1 + row_bytes)] not in {0, 1, 2, 3, 4}
            for row in range(height)
        )
    ):
        return None
    return content, width, height


_SENSITIVE_KEY_PATTERN = re.compile(
    r"^(?:(?:[a-z0-9]+[_-])*(?:authorization|cookie|password|passwd|secret|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"credential|credentials|host[_-]?path|local[_-]?path|private[_-]?key|"
    r"private[_-]?locator|remote[_-]?path|runner[_-]?config|source[_-]?uri|"
    r"storage[_-]?uri|connection[_-]?string|token)|"
    r"aws[_-]?secret[_-]?(?:access[_-]?)?key|"
    r"azure[_-]?storage[_-]?connection[_-]?string|google[_-]?application[_-]?"
    r"credentials|mysql[_-]?pwd|rediscli[_-]?auth|pgpassword|database[_-]?url|"
    r"accountkey|(?:[a-z0-9]+[_-])*(?:password|private[_-]?key)"
    r"[_-](?:data|file|value))$",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/-]+|"
    r"\b(?:authorization|set[_-]?cookie|cookie)\s*[:=]\s*[^\r\n]+|"
    r"\bsk-(?:ant-)?[A-Za-z0-9_-]{12,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"\b(?:(?:[a-z0-9]+[_-])*(?:api[_-]?key|client[_-]?secret|password|"
    r"secret|access[_-]?token|refresh[_-]?token|credential|private[_-]?key|"
    r"token)|aws[_-]?secret[_-]?(?:access[_-]?)?key|"
    r"azure[_-]?storage[_-]?connection[_-]?string|"
    r"google[_-]?application[_-]?credentials|mysql[_-]?pwd|rediscli[_-]?auth|"
    r"pgpassword|database[_-]?url|accountkey)"
    r"\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
_HOST_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._/\\-])(?:/(?:cluster|gpfs|home|lustre|mnt|private|root|"
    r"scratch|tmp|Users)(?:/|$)|"
    r"[A-Za-z]:[\\/]|\\\\[A-Za-z0-9_.-]+\\|file://)",
    re.IGNORECASE,
)
_PRIVATE_URL_PATTERN = re.compile(
    r"https?://(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
    r"\[?::1\]?)(?::\d+)?(?:[/\s]|$)",
    re.IGNORECASE,
)
_HTTP_URL_PATTERN = re.compile(r"(?i)https?://[^\s\"'<>]+")
_PRIVATE_LOCATOR_PATTERN = re.compile(
    r"(?i)(?:storage|s3|gs|gcs|azure|ssh|scp|file|postgres|postgresql|redis|"
    r"mongodb(?:\+srv)?|mysql|mariadb|amqp|amqps)://[^\s\"'<>]*"
)
_ENCODED_PRIVATE_LOCATION_PATTERN = re.compile(
    r"(?i)(?:\\/|%2f)(?:cluster|gpfs|home|lustre|mnt|private|root|scratch|"
    r"tmp|Users)(?:\\/|%2f)"
)
_CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SAFE_PUBLIC_METADATA_KEYS = frozenset(
    {
        "credential_count",
        "credential_present",
        "credential_slots",
        "credentials_ready",
        "token_count",
        "token_limit",
        "token_usage",
    }
)
_SENSITIVE_COMPACT_KEY_ALIASES = frozenset(
    {
        "accountkey",
        "awssecretaccesskey",
        "awssecretkey",
        "azurestorageconnectionstring",
        "databaseurl",
        "googleapplicationcredentials",
        "mysqlpwd",
        "pgpassword",
        "rediscliauth",
    }
)
_SCIENCE_SUFFIXES = {
    ".a2m",
    ".afa",
    ".aln",
    ".csv",
    ".fa",
    ".faa",
    ".fasta",
    ".hmm",
    ".jsonl",
    ".sqlite",
    ".sqlite3",
    ".sto",
}
_SCIENCE_NAME_MARKERS = (
    "aox",
    "candidate",
    "cluster",
    "evidence",
    "hit",
    "motif",
    "report",
)
_IDENTITY_DIGEST_FIELDS = (
    "config_digest",
    "scoring_contract_digest",
    "scoring_implementation_digest",
    "image_digest",
    "sdk_digest",
)
_IDENTITY_FIELDS = (
    "git_commit",
    "config_digest",
    "workflow_ref",
    "scoring_contract_digest",
    "scoring_implementation_digest",
    "image_digest",
    "sdk_digest",
)
_ALLOWED_PREREQUISITE_KEYS = {
    "config_digest",
    "credential_slots",
    "git_commit",
    "image_digest",
    "ncbi_identity",
    "prompt_accessions",
    "sdk_digest",
    "toolchain_image_digests",
    "workflow_ref",
}
_BLANK_WORLD_ROOT_PROOF_KEYS = {
    "allowed_prerequisite_digest",
    "allowed_prerequisites",
    "architecture_qualification",
    "attempt_kind",
    "evidence_cache_reuse",
    "hpc_workspace_label",
    "initial_entries",
    "launch_id",
    "provider_cache_mode",
    "root_identity",
    "root_names",
    "schema_id",
    "sqlite_preexisting",
}
_LEGACY_BLANK_WORLD_ROOT_PROOF_KEYS = (
    _BLANK_WORLD_ROOT_PROOF_KEYS - {"launch_id"}
) | {"attempt_id"}
AOX_TOOLCHAIN_RUNTIME_CONTRACTS: dict[str, dict[str, str]] = {
    "mafft": {
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
    },
    "hmmbuild": {
        "toolchain_id": "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1",
        "tool_id": "bio_tools.hmmbuild",
        "adapter_id": "bio_tools.hmmbuild",
        "command_template_id": "bio_tools_hmmbuild_sif_v1",
    },
    "hmmalign": {
        "toolchain_id": "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1",
        "tool_id": "bio_tools.hmmalign",
        "adapter_id": "bio_tools.hmmalign",
        "command_template_id": "bio_tools_hmmalign_sif_v1",
    },
    "cd-hit": {
        "toolchain_id": "cdhit_4.8.1.hpc_apptainer_sif:v1",
        "tool_id": "bio_tools.cdhit",
        "adapter_id": "bio_tools.cdhit",
        "command_template_id": "bio_tools_cdhit_sif_v2",
    },
}
AOX_HPC_WORKSPACE_BINDING_CONTRACT_ID = "aox_hpc_workspace_binding@1"
_HPC_WORKSPACE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_REQUIRED_CREDENTIAL_SLOTS = frozenset({"llm", "ncbi", "semantic_scholar", "tavily"})
_EXPECTED_PROMPT_ACCESSIONS = {
    "formal_ncbi": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
    "probe_ncbi": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
    "probe_uniprot": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
}
_REQUIRED_PROVIDER_IDS = {"pubmed", "ncbi", "ebi_hmmer", "uniprot"}
_REQUIRED_TOOL_IDS = {"mafft", "hmmbuild", "hmmalign", "cd-hit"}
_REQUIRED_TASK_ROLES = {"researcher", "executor", "reporter"}
_HMMER_UPSTREAM_EMPTY_STAGE = "pre_uniprot_score_filter"
_S12_OPERATION_IDENTITY_KEYS = {
    "schema_version",
    "sandbox_workspace_id",
    "source_snapshot_digest",
    "sdk_module",
    "function_name",
    "params_digest",
    "input_artifact_ids",
    "input_artifact_digests",
    "placement",
    "hpc_workspace_id",
    "stage_refs",
    "selected_backend",
    "route_reason",
    "route_policy_id",
    "runtime_packaging_id",
    "toolchain_id",
    "provider_config_digest",
    "resource_class",
    "resource_estimate",
    "expected_outputs",
    "planned_fetch_intent",
    "approval_requirement",
}
_SANDBOX_CALCULATION_IDENTITY_KEYS = {
    "schema_version",
    "sandbox_run_id",
    "sandbox_workspace_id",
    "source_snapshot_artifact_id",
    "source_snapshot_digest",
    "calculation_id",
    "calculation_contract_digest",
    "calculation_implementation_digest",
    "params_digest",
    "input_artifact_ids",
    "input_artifact_digests",
    "output_artifact_ids",
    "output_artifact_digests",
}


def aox_hpc_workspace_id(
    *,
    sandbox_workspace_id: str,
    hpc_workspace_label: str,
) -> str:
    """Reproduce the versioned, reversible-label HPC workspace identity contract."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", sandbox_workspace_id) is None:
        raise ValueError("sandbox workspace id is not a canonical public id")
    if _HPC_WORKSPACE_LABEL_PATTERN.fullmatch(hpc_workspace_label) is None:
        raise ValueError("HPC workspace label must already be normalized")
    digest = hashlib.sha256(
        f"{sandbox_workspace_id}:{hpc_workspace_label}".encode("utf-8")
    ).hexdigest()[:16]
    return f"hpcws_{digest}"


class CutoverEvidenceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(f"{code}: {message}")


def _normalize_architecture_qualification(
    receipt: Mapping[str, object],
    *,
    expected_source_commit: str,
) -> dict[str, str]:
    try:
        return normalize_architecture_qualification_receipt(
            receipt,
            expected_source_commit=expected_source_commit,
        )
    except AoxArchitectureQualificationError as exc:
        raise CutoverEvidenceError(
            exc.code,
            "AOX evidence carries invalid architecture qualification",
            details=exc.details,
        ) from exc


@dataclass(frozen=True, slots=True)
class BlankWorldRoots:
    launch_id: str
    attempt_kind: str
    attempt_root: Path
    sqlite_path: Path
    artifact_root: Path
    blob_root: Path
    sandbox_root: Path
    hpc_root: Path
    evidence_root: Path
    hpc_workspace_label: str
    proof: dict[str, Any]

    def local_paths(self) -> dict[str, Path]:
        return {
            "attempt_root": self.attempt_root,
            "sqlite_path": self.sqlite_path,
            "artifact_root": self.artifact_root,
            "blob_root": self.blob_root,
            "sandbox_root": self.sandbox_root,
            "hpc_root": self.hpc_root,
            "evidence_root": self.evidence_root,
        }


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    code: str
    identity: str
    message: str
    expected: object | None = None
    actual: object | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "identity": self.identity,
            "message": self.message,
        }
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.actual is not None:
            payload["actual"] = self.actual
        return payload


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    bundle_digest: str | None
    attempt_id: str | None
    attempt_kind: str | None
    issues: tuple[VerificationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "aox_blank_world_verification@1",
            "passed": self.passed,
            "bundle_digest": self.bundle_digest,
            "attempt_id": self.attempt_id,
            "attempt_kind": self.attempt_kind,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class _SimilarityValidationParameters:
    threshold_ppm: int
    empty_result_reason: str | None
    calculation_id: str
    calculation_digest: str
    implementation_digest: str
    candidate_fasta_digest: str
    membership_digest: str


@dataclass(frozen=True, slots=True)
class _VerifiedSimilarityGraph:
    artifact_bindings: tuple[tuple[str, str, str], ...]
    parameters: _SimilarityValidationParameters
    graph_result: Any


@dataclass(frozen=True, slots=True)
class AttemptRunRecord:
    attempt_id: str
    attempt_kind: str
    bundle_path: Path
    artifact_root: Path
    bundle_digest: str
    verification: VerificationResult

def canonical_json_bytes(payload: object) -> bytes:
    _reject_non_finite(payload, identity="payload")
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(payload: object) -> str:
    return _sha256(canonical_json_bytes(payload))


def _safe_source_tree_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CutoverEvidenceError(
            "sealed_source_tree_path_invalid",
            "sealed source-tree entries require safe POSIX relative paths",
        )
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise CutoverEvidenceError(
            "sealed_source_tree_path_invalid",
            "sealed source-tree entries require safe POSIX relative paths",
        )
    return value


def _source_tree_digest(file_entries: list[dict[str, object]]) -> str:
    """Match ArtifactBoundaryService's persisted source-tree digest contract."""

    return _sha256(
        json.dumps(file_entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def verify_sealed_source_tree_envelope(
    content: bytes,
    *,
    expected_source_tree_digest: str,
) -> dict[str, object]:
    """Strictly decode and recompute a sealed source-tree evidence envelope."""

    try:
        envelope = _strict_json_loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "sealed_source_tree_envelope_invalid",
            "sealed source-tree evidence is not strict UTF-8 JSON",
        ) from exc
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"schema_id", "source_tree_digest", "files"}
        or envelope.get("schema_id") != SEALED_SOURCE_TREE_SCHEMA_ID
        or not isinstance(envelope.get("files"), list)
        or not envelope["files"]
    ):
        raise CutoverEvidenceError(
            "sealed_source_tree_envelope_invalid",
            "sealed source-tree evidence has an unsupported closed schema",
        )
    if content != canonical_json_bytes(envelope) + b"\n":
        raise CutoverEvidenceError(
            "sealed_source_tree_envelope_noncanonical",
            "sealed source-tree evidence is not canonical JSON",
        )
    declared_tree_digest = envelope.get("source_tree_digest")
    if (
        not isinstance(declared_tree_digest, str)
        or _DIGEST_PATTERN.fullmatch(declared_tree_digest) is None
        or _DIGEST_PATTERN.fullmatch(expected_source_tree_digest) is None
    ):
        raise CutoverEvidenceError(
            "sealed_source_tree_digest_invalid",
            "sealed source-tree digest is not a canonical SHA-256 identity",
        )
    normalized_files: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(envelope["files"]):
        if not isinstance(raw, dict) or set(raw) != {
            "relative_path",
            "size_bytes",
            "content_digest",
            "content_base64",
        }:
            raise CutoverEvidenceError(
                "sealed_source_tree_file_invalid",
                "sealed source-tree file entry has an unsupported closed schema",
                details={"index": index},
            )
        relative_path = _safe_source_tree_relative_path(raw.get("relative_path"))
        size_bytes = raw.get("size_bytes")
        content_digest = raw.get("content_digest")
        content_base64 = raw.get("content_base64")
        if (
            relative_path in seen_paths
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or not isinstance(content_digest, str)
            or _DIGEST_PATTERN.fullmatch(content_digest) is None
            or not isinstance(content_base64, str)
        ):
            raise CutoverEvidenceError(
                "sealed_source_tree_file_invalid",
                "sealed source-tree file identity is malformed or duplicated",
                details={"index": index},
            )
        seen_paths.add(relative_path)
        try:
            file_content = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise CutoverEvidenceError(
                "sealed_source_tree_file_invalid",
                "sealed source-tree file bytes are not canonical base64",
                details={"relative_path": relative_path},
            ) from exc
        if (
            base64.b64encode(file_content).decode("ascii") != content_base64
            or len(file_content) != size_bytes
            or _sha256(file_content) != content_digest
        ):
            raise CutoverEvidenceError(
                "sealed_source_tree_file_digest_mismatch",
                "sealed source-tree file bytes do not reproduce size and digest",
                details={"relative_path": relative_path},
            )
        try:
            source_text = file_content.decode("utf-8")
        except UnicodeDecodeError:
            source_text = None
        if source_text is not None:
            _assert_public_safe(
                source_text,
                identity=f"sealed_source_tree:{relative_path}",
            )
        normalized_files.append(
            {
                "relative_path": relative_path,
                "content_digest": content_digest,
                "size_bytes": size_bytes,
            }
        )
    ordered_paths = [str(item["relative_path"]) for item in normalized_files]
    if ordered_paths != sorted(ordered_paths):
        raise CutoverEvidenceError(
            "sealed_source_tree_file_order_invalid",
            "sealed source-tree file entries are not sorted by relative path",
        )
    actual_tree_digest = _source_tree_digest(normalized_files)
    if (
        actual_tree_digest != declared_tree_digest
        or declared_tree_digest != expected_source_tree_digest
    ):
        raise CutoverEvidenceError(
            "sealed_source_tree_digest_mismatch",
            "sealed source-tree files do not reproduce declared and provenance digests",
            details={
                "expected": expected_source_tree_digest,
                "declared": declared_tree_digest,
                "actual": actual_tree_digest,
            },
        )
    return dict(envelope)


def _validate_delegation_workflow_bindings(payload: Mapping[str, Any]) -> None:
    tasks = [dict(item) for item in payload.get("tasks") or []]
    by_role = {
        str(task.get("role") or ""): task
        for task in tasks
        if str(task.get("role") or "") in _REQUIRED_TASK_ROLES
    }
    if set(by_role) != _REQUIRED_TASK_ROLES:
        raise CutoverEvidenceError(
            "delegation_workflow_binding_missing",
            "workflow binding receipts require one researcher, executor, and reporter task",
            details={"identity": "tasks.workflow_refs"},
        )
    workflow_ref = str(dict(payload.get("identity") or {}).get("workflow_ref") or "")
    seen_request_refs: set[str] = set()
    for role, task in by_role.items():
        request_ref = task.get("delegation_request_ref")
        request_digest = task.get("delegation_request_digest")
        request_projection_raw = task.get("delegation_request")
        request_projection = (
            dict(request_projection_raw)
            if isinstance(request_projection_raw, dict)
            else {}
        )
        workflow_refs = task.get("workflow_refs")
        workflow_manifests = task.get("workflow_manifests")
        expected_refs = [workflow_ref] if role == "executor" else []
        if (
            not isinstance(request_ref, str)
            or not request_ref
            or request_ref in seen_request_refs
            or not isinstance(request_digest, str)
            or _DIGEST_PATTERN.fullmatch(request_digest) is None
            or set(request_projection) != _DELEGATION_REQUEST_PROJECTION_KEYS
            or request_projection.get("schema_id")
            != FORMAL_DELEGATION_REQUEST_SCHEMA_ID
            or request_projection.get("document_kind") != "delegation_request"
            or request_projection.get("document_id") != request_ref
            or request_projection.get("task_id") != task.get("task_id")
            or request_projection.get("role") != role
            or not isinstance(request_projection.get("instructions_digest"), str)
            or _DIGEST_PATTERN.fullmatch(
                str(request_projection.get("instructions_digest") or "")
            )
            is None
            or any(
                not isinstance(request_projection.get(key), str)
                or not str(request_projection.get(key) or "")
                for key in ("agent_id", "nickname", "display_name", "handle")
            )
            or task.get("assigned_ref") != request_projection.get("agent_id")
            or request_projection.get("workflow_refs") != workflow_refs
            or request_projection.get("workflow_manifests") != workflow_manifests
            or canonical_digest(request_projection) != request_digest
            or workflow_refs != expected_refs
            or not isinstance(workflow_manifests, list)
        ):
            raise CutoverEvidenceError(
                "delegation_workflow_binding_invalid",
                "durable delegation workflow receipts are malformed or not executor-scoped",
                details={"identity": f"task:{task.get('task_id')}:workflow_refs"},
            )
        seen_request_refs.add(request_ref)
        _assert_public_safe(
            request_projection,
            identity=f"task:{task.get('task_id')}:delegation_request",
        )
        if role != "executor":
            if workflow_manifests:
                raise CutoverEvidenceError(
                    "delegation_workflow_binding_invalid",
                    "researcher and reporter delegation must not inherit workflow manifests",
                    details={
                        "identity": f"task:{task.get('task_id')}:workflow_manifests"
                    },
                )
            continue
        if len(workflow_manifests) != 1 or not isinstance(workflow_manifests[0], dict):
            raise CutoverEvidenceError(
                "delegation_workflow_manifest_invalid",
                "executor delegation requires exactly one pinned workflow manifest snapshot",
                details={"identity": f"task:{task.get('task_id')}:workflow_manifests"},
            )
        manifest = dict(workflow_manifests[0])
        expected_manifest_keys = {
            "workflow_id",
            "version",
            "content_sha256",
            "title",
            "summary",
            "capability_requirements",
            "tool_requirements",
            "knowledge_refs",
            "manifest_path",
            "selection_ref",
        }
        core_manifest = {
            key: manifest.get(key)
            for key in (
                "workflow_id",
                "version",
                "content_sha256",
                "title",
                "summary",
                "capability_requirements",
                "tool_requirements",
                "knowledge_refs",
            )
        }
        expected_selection_ref = (
            f"workflow:{manifest.get('workflow_id')}@{manifest.get('version')}"
            f"#{manifest.get('content_sha256')}"
        )
        knowledge_refs = manifest.get("knowledge_refs")
        manifest_path = manifest.get("manifest_path")
        if (
            set(manifest) != expected_manifest_keys
            or manifest.get("selection_ref") != workflow_ref
            or expected_selection_ref != workflow_ref
            or workflow_manifest_content_sha256(core_manifest)
            != manifest.get("content_sha256")
            or not isinstance(manifest_path, str)
            or not manifest_path
            or PurePosixPath(manifest_path).is_absolute()
            or any(
                part in {"", ".", ".."} for part in PurePosixPath(manifest_path).parts
            )
            or not isinstance(knowledge_refs, list)
            or not knowledge_refs
            or any(
                not isinstance(reference, dict)
                or set(reference) != {"doc_id", "version", "content_sha256"}
                or not str(reference.get("doc_id") or "")
                or not str(reference.get("version") or "")
                or _DIGEST_PATTERN.fullmatch(str(reference.get("content_sha256") or ""))
                is None
                for reference in knowledge_refs
            )
        ):
            raise CutoverEvidenceError(
                "delegation_workflow_manifest_invalid",
                "executor delegation manifest snapshot does not reproduce the campaign workflow ref",
                details={"identity": f"task:{task.get('task_id')}:workflow_manifests"},
            )


def controlled_operation_digest(material: Mapping[str, object]) -> str:
    normalized = dict(material)
    if set(normalized) != _S12_OPERATION_IDENTITY_KEYS:
        raise CutoverEvidenceError(
            "operation_identity_material_invalid",
            "controlled operation identity material must match the complete S12 digest contract",
            details={
                "missing": sorted(_S12_OPERATION_IDENTITY_KEYS - set(normalized)),
                "unexpected": sorted(set(normalized) - _S12_OPERATION_IDENTITY_KEYS),
            },
        )
    if normalized.get("schema_version") != "s12.adapter_envelope.v1":
        raise CutoverEvidenceError(
            "operation_identity_material_invalid",
            "controlled operation identity material has an unsupported schema",
            details={"identity": "operation_identity_material.schema_version"},
        )
    _reject_non_finite(normalized, identity="operation_identity_material")
    content = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256(content)


def sandbox_calculation_digest(material: Mapping[str, object]) -> str:
    normalized = dict(material)
    if set(normalized) != _SANDBOX_CALCULATION_IDENTITY_KEYS:
        raise CutoverEvidenceError(
            "sandbox_calculation_identity_material_invalid",
            "sandbox calculation identity material must match the complete receipt contract",
            details={
                "missing": sorted(_SANDBOX_CALCULATION_IDENTITY_KEYS - set(normalized)),
                "unexpected": sorted(
                    set(normalized) - _SANDBOX_CALCULATION_IDENTITY_KEYS
                ),
            },
        )
    if normalized.get("schema_version") != "openzyme_sandbox_calculation_receipt@1":
        raise CutoverEvidenceError(
            "sandbox_calculation_identity_material_invalid",
            "sandbox calculation identity material has an unsupported schema",
            details={"identity": "operation_identity_material.schema_version"},
        )
    _reject_non_finite(normalized, identity="sandbox_calculation_identity_material")
    return canonical_digest(normalized)


def _control_plane_json_digest(payload: object) -> str:
    _reject_non_finite(payload, identity="control_plane_identity")
    return _sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    )


def operation_identity_digest(operation: Mapping[str, object]) -> str:
    material = operation.get("operation_identity_material")
    if isinstance(material, Mapping):
        if operation.get("canonical_ref_kind") == "sandbox_calculation":
            return sandbox_calculation_digest(material)
        return controlled_operation_digest(material)
    inputs = [dict(item) for item in operation.get("inputs") or []]
    outputs = [dict(item) for item in operation.get("outputs") or []]
    material = {
        "operation_id": str(operation.get("operation_id") or ""),
        "kind": str(operation.get("kind") or ""),
        "scope": str(operation.get("scope") or ""),
        "route_policy_id": str(operation.get("route_policy_id") or ""),
        "selected_backend": str(operation.get("selected_backend") or ""),
        "source_snapshot_digest": str(operation.get("source_snapshot_digest") or ""),
        "inputs": inputs,
        "parameters": dict(operation.get("parameters") or {}),
        "expected_output_artifact_ids": [
            str(item.get("artifact_id") or "") for item in outputs
        ],
    }
    return canonical_digest(material)


def _validate_sandbox_calculation_identity(
    operation: Mapping[str, object],
) -> None:
    operation_id = str(operation.get("operation_id") or "")
    raw_material = operation.get("operation_identity_material")
    if not isinstance(raw_material, Mapping):
        raise CutoverEvidenceError(
            "sandbox_calculation_identity_material_missing",
            "sandbox calculation evidence must carry its complete receipt material",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )
    material = dict(raw_material)
    actual_digest = sandbox_calculation_digest(material)
    inputs = [
        dict(item)
        for item in operation.get("inputs") or []
        if isinstance(item, Mapping)
    ]
    outputs = [
        dict(item)
        for item in operation.get("outputs") or []
        if isinstance(item, Mapping)
    ]
    digest_fields = (
        "source_snapshot_digest",
        "calculation_contract_digest",
        "calculation_implementation_digest",
        "params_digest",
    )
    if (
        operation.get("operation_identity_schema")
        != "openzyme_sandbox_calculation_receipt@1"
        or operation.get("operation_identity_digest") != actual_digest
        or operation.get("backend_run_id") != material.get("sandbox_run_id")
        or operation.get("source_snapshot_digest")
        != material.get("source_snapshot_digest")
        or operation.get("params_digest") != material.get("params_digest")
        or material.get("input_artifact_ids")
        != [str(item.get("artifact_id") or "") for item in inputs]
        or material.get("input_artifact_digests")
        != [str(item.get("content_digest") or "") for item in inputs]
        or material.get("output_artifact_ids")
        != [str(item.get("artifact_id") or "") for item in outputs]
        or material.get("output_artifact_digests")
        != [str(item.get("content_digest") or "") for item in outputs]
        or not str(material.get("sandbox_workspace_id") or "")
        or not str(material.get("source_snapshot_artifact_id") or "")
        or not str(material.get("calculation_id") or "")
        or any(
            _DIGEST_PATTERN.fullmatch(str(material.get(field) or "")) is None
            for field in digest_fields
        )
    ):
        raise CutoverEvidenceError(
            "sandbox_calculation_identity_material_mismatch",
            "sandbox calculation evidence differs from its run-bound receipt material",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )
    parameters = operation.get("parameters")
    if isinstance(parameters, Mapping) and canonical_digest(
        dict(parameters)
    ) != material.get("params_digest"):
        raise CutoverEvidenceError(
            "sandbox_calculation_params_digest_mismatch",
            "sandbox calculation parameters do not reproduce params_digest",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )


def _validate_operation_identity(operation: Mapping[str, object]) -> None:
    canonical_ref_kind = operation.get("canonical_ref_kind")
    if canonical_ref_kind == "sandbox_calculation":
        _validate_sandbox_calculation_identity(operation)
        return
    if canonical_ref_kind != "controlled_operation":
        raise CutoverEvidenceError(
            "operation_canonical_ref_kind_invalid",
            "operation evidence must identify its real canonical owner",
            details={
                "identity": f"operation:{operation.get('operation_id') or 'missing'}"
            },
        )
    _validate_controlled_operation_identity(operation)


def _validate_controlled_operation_identity(
    operation: Mapping[str, object],
) -> None:
    operation_id = str(operation.get("operation_id") or "")
    raw_material = operation.get("operation_identity_material")
    if not isinstance(raw_material, Mapping):
        raise CutoverEvidenceError(
            "operation_identity_material_missing",
            "attempt operations must carry the exact public S12 control-plane digest material",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )
    material = dict(raw_material)
    actual_digest = controlled_operation_digest(material)
    if operation.get("operation_identity_digest") != actual_digest:
        raise CutoverEvidenceError(
            "operation_identity_mismatch",
            "operation identity digest differs from the control-plane S12 material",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )
    inputs = [
        dict(item)
        for item in operation.get("inputs") or []
        if isinstance(item, Mapping)
    ]
    if (
        operation.get("operation_identity_schema")
        != "openzyme_controlled_operation_s12@1"
        or material.get("source_snapshot_digest")
        != operation.get("source_snapshot_digest")
        or material.get("route_policy_id") != operation.get("route_policy_id")
        or material.get("selected_backend") != operation.get("selected_backend")
        or material.get("input_artifact_ids")
        != [str(item.get("artifact_id") or "") for item in inputs]
        or material.get("input_artifact_digests")
        != [str(item.get("content_digest") or "") for item in inputs]
        or material.get("params_digest") != operation.get("params_digest")
        or not str(material.get("sandbox_workspace_id") or "")
        or not str(material.get("sdk_module") or "")
        or not str(material.get("function_name") or "")
        or not str(material.get("route_reason") or "")
        or not str(material.get("runtime_packaging_id") or "")
        or not str(material.get("resource_class") or "")
        or not isinstance(material.get("resource_estimate"), dict)
        or not isinstance(material.get("expected_outputs"), dict)
        or not isinstance(material.get("planned_fetch_intent"), dict)
        or not isinstance(material.get("approval_requirement"), dict)
    ):
        raise CutoverEvidenceError(
            "operation_identity_material_mismatch",
            "operation evidence does not match its control-plane S12 identity material",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )
    parameters = operation.get("parameters")
    if isinstance(parameters, dict) and material.get(
        "params_digest"
    ) != _control_plane_json_digest(parameters):
        raise CutoverEvidenceError(
            "operation_parameter_projection_mismatch",
            "safe operation parameters do not reproduce the control-plane params digest",
            details={"identity": f"operation:{operation_id or 'missing'}"},
        )


def normalize_aox_cutover_prerequisites(
    allowed_prerequisites: Mapping[str, object],
    *,
    identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    prerequisites = dict(allowed_prerequisites)
    actual_keys = set(prerequisites)
    missing = sorted(_ALLOWED_PREREQUISITE_KEYS - actual_keys)
    extra = sorted(str(key) for key in actual_keys - _ALLOWED_PREREQUISITE_KEYS)
    if missing or extra:
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "blank-world prerequisites must contain the exact identity-only schema",
            details={"missing": missing, "extra": extra},
        )

    scalar_fields = (
        "git_commit",
        "config_digest",
        "workflow_ref",
        "image_digest",
        "sdk_digest",
    )
    for key in scalar_fields:
        if not isinstance(prerequisites[key], str):
            raise CutoverEvidenceError(
                "allowed_prerequisite_schema_invalid",
                "blank-world prerequisite identity fields must be strings",
                details={"identity": f"allowed_prerequisites.{key}"},
            )
    if re.fullmatch(r"[0-9a-f]{40}", str(prerequisites["git_commit"])) is None:
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "blank-world git prerequisite must be a full lowercase commit id",
            details={"identity": "allowed_prerequisites.git_commit"},
        )
    for key in ("config_digest", "image_digest", "sdk_digest"):
        if _DIGEST_PATTERN.fullmatch(str(prerequisites[key])) is None:
            raise CutoverEvidenceError(
                "allowed_prerequisite_schema_invalid",
                "blank-world prerequisite digest is malformed",
                details={"identity": f"allowed_prerequisites.{key}"},
            )
    if (
        re.fullmatch(
            r"workflow:[a-z0-9][a-z0-9._-]*@[0-9]+\.[0-9]+\.[0-9]+#sha256:[0-9a-f]{64}",
            str(prerequisites["workflow_ref"]),
        )
        is None
    ):
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "blank-world workflow prerequisite must be a full digest-pinned ref",
            details={"identity": "allowed_prerequisites.workflow_ref"},
        )

    toolchain_digests = prerequisites["toolchain_image_digests"]
    if not isinstance(toolchain_digests, dict):
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "toolchain image prerequisites must be an exact toolchain-id mapping",
            details={"identity": "allowed_prerequisites.toolchain_image_digests"},
        )
    expected_toolchain_ids = {
        item["toolchain_id"] for item in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.values()
    }
    if set(toolchain_digests) != expected_toolchain_ids or any(
        not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None
        for value in toolchain_digests.values()
    ):
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "toolchain image prerequisites must bind the exact four AOX SIF identities",
            details={
                "identity": "allowed_prerequisites.toolchain_image_digests",
                "expected_toolchain_ids": sorted(expected_toolchain_ids),
            },
        )
    hmmbuild_id = AOX_TOOLCHAIN_RUNTIME_CONTRACTS["hmmbuild"]["toolchain_id"]
    hmmalign_id = AOX_TOOLCHAIN_RUNTIME_CONTRACTS["hmmalign"]["toolchain_id"]
    if toolchain_digests[hmmbuild_id] != toolchain_digests[hmmalign_id]:
        raise CutoverEvidenceError(
            "allowed_prerequisite_hmmer_image_drift",
            "hmmbuild and hmmalign must bind the same HMMER SIF content digest",
            details={"identity": "allowed_prerequisites.toolchain_image_digests"},
        )

    credential_slots = prerequisites["credential_slots"]
    if (
        not isinstance(credential_slots, dict)
        or set(credential_slots) != _REQUIRED_CREDENTIAL_SLOTS
        or any(type(value) is not bool for value in credential_slots.values())
        or credential_slots.get("llm") is not True
        or credential_slots.get("ncbi") is not True
    ):
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "credential prerequisites must expose the exact availability-only slots",
            details={"identity": "allowed_prerequisites.credential_slots"},
        )
    ncbi_identity = prerequisites["ncbi_identity"]
    if (
        not isinstance(ncbi_identity, str)
        or _DIGEST_PATTERN.fullmatch(ncbi_identity) is None
    ):
        raise CutoverEvidenceError(
            "allowed_prerequisite_schema_invalid",
            "NCBI identity prerequisite must be an opaque digest",
            details={"identity": "allowed_prerequisites.ncbi_identity"},
        )
    prompt_accessions = prerequisites["prompt_accessions"]
    if (
        not isinstance(prompt_accessions, dict)
        or prompt_accessions != _EXPECTED_PROMPT_ACCESSIONS
    ):
        raise CutoverEvidenceError(
            "allowed_prerequisite_prompt_accessions_drift",
            "prompt accessions must exactly match the formal and probe contracts",
            details={"identity": "allowed_prerequisites.prompt_accessions"},
        )

    if identity is not None:
        normalized_identity = _normalize_identity(identity)
        drift = {
            key: {
                "expected": normalized_identity[key],
                "actual": prerequisites[key],
            }
            for key in scalar_fields
            if prerequisites[key] != normalized_identity[key]
        }
        if drift:
            raise CutoverEvidenceError(
                "allowed_prerequisite_identity_drift",
                "blank-world prerequisites differ from the campaign identity",
                details={"drift": drift},
            )
    _assert_public_safe(prerequisites, identity="allowed_prerequisites")
    return prerequisites


def assert_formal_campaign_root(campaign_root: Path) -> None:
    requested = campaign_root.expanduser()
    lineage = (requested, *requested.parents)
    marker_found = any(
        (candidate / DIAGNOSTIC_ROOT_MARKER_FILENAME).exists()
        or (candidate / DIAGNOSTIC_ROOT_MARKER_FILENAME).is_symlink()
        for candidate in lineage
    )
    if (
        requested.is_symlink()
        or requested.name.startswith(DIAGNOSTIC_RUN_POLICY.root_namespace_prefix or "")
        or marker_found
    ):
        raise CutoverEvidenceError(
            "formal_campaign_diagnostic_root_forbidden",
            "formal acceptance rejects every diagnostic root namespace",
        )


def create_blank_world_roots(
    campaign_root: Path,
    *,
    launch_id: str,
    attempt_kind: str,
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
) -> BlankWorldRoots:
    if attempt_kind not in {"positive", "fault"}:
        raise CutoverEvidenceError(
            "attempt_kind_invalid",
            "blank-world attempt kind must be positive or fault",
            details={"attempt_kind": attempt_kind},
        )
    if re.fullmatch(r"formal-slot-[a-f0-9]{24}", launch_id) is None:
        raise CutoverEvidenceError(
            "launch_id_invalid",
            "blank-world roots require an exact claimed formal launch id",
            details={"launch_id": launch_id},
        )
    assert_formal_campaign_root(campaign_root)
    prerequisites = normalize_aox_cutover_prerequisites(allowed_prerequisites)
    qualification = _normalize_architecture_qualification(
        architecture_qualification,
        expected_source_commit=str(prerequisites["git_commit"]),
    )
    base = campaign_root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    attempt_root = base / launch_id
    if attempt_root.exists():
        preloaded = _preloaded_science(attempt_root)
        if preloaded:
            raise CutoverEvidenceError(
                "preloaded_science_detected",
                "the requested attempt root already contains scientific evidence",
                details={"entries": preloaded},
            )
        raise CutoverEvidenceError(
            "attempt_root_not_new",
            "every formal launch must use a newly created root",
            details={"launch_id": launch_id},
        )
    attempt_root.mkdir(mode=0o700)
    if attempt_root.is_symlink():
        raise CutoverEvidenceError(
            "attempt_root_symlink_forbidden",
            "blank-world attempt root must not be a symlink",
        )
    root_names = {
        "artifact": "artifacts",
        "blob": "blobs",
        "sandbox": "sandboxes",
        "hpc": "hpc-workspace",
        "evidence": "evidence",
    }
    roots: dict[str, Path] = {}
    for root_kind, name in root_names.items():
        path = attempt_root / name
        path.mkdir(mode=0o700)
        roots[root_kind] = path
    sqlite_path = attempt_root / "control-plane.sqlite3"
    hpc_workspace_label = "aox-cutover-" + uuid4().hex
    prerequisite_digest = canonical_digest(prerequisites)
    root_identity = canonical_digest(
        {
            "launch_id": launch_id,
            "attempt_kind": attempt_kind,
            "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
            "nonce": uuid4().hex,
            "root_names": root_names,
            "hpc_workspace_label": hpc_workspace_label,
        }
    )
    proof = {
        "schema_id": BLANK_WORLD_ROOT_PROOF_SCHEMA_ID,
        "architecture_qualification": qualification,
        "launch_id": launch_id,
        "attempt_kind": attempt_kind,
        "root_identity": root_identity,
        "root_names": root_names,
        "initial_entries": {
            "sqlite": 0,
            **{root_kind: 0 for root_kind in root_names},
        },
        "sqlite_preexisting": False,
        "provider_cache_mode": "bypass",
        "evidence_cache_reuse": False,
        "hpc_workspace_label": hpc_workspace_label,
        "allowed_prerequisite_digest": prerequisite_digest,
        "allowed_prerequisites": prerequisites,
    }
    validate_blank_world_roots(
        attempt_root=attempt_root,
        sqlite_path=sqlite_path,
        roots=roots,
    )
    return BlankWorldRoots(
        launch_id=launch_id,
        attempt_kind=attempt_kind,
        attempt_root=attempt_root,
        sqlite_path=sqlite_path,
        artifact_root=roots["artifact"],
        blob_root=roots["blob"],
        sandbox_root=roots["sandbox"],
        hpc_root=roots["hpc"],
        evidence_root=roots["evidence"],
        hpc_workspace_label=hpc_workspace_label,
        proof=proof,
    )


def validate_blank_world_roots(
    *,
    attempt_root: Path,
    sqlite_path: Path,
    roots: Mapping[str, Path],
) -> None:
    resolved_attempt = attempt_root.resolve()
    if sqlite_path.exists():
        raise CutoverEvidenceError(
            "blank_world_sqlite_not_empty",
            "control-plane SQLite must not exist before attempt initialization",
        )
    for kind, path in roots.items():
        resolved = path.resolve()
        if resolved_attempt not in resolved.parents:
            raise CutoverEvidenceError(
                "blank_world_root_escape",
                "a blank-world root escapes the attempt root",
                details={"root_kind": kind},
            )
        if path.is_symlink() or not path.is_dir():
            raise CutoverEvidenceError(
                "blank_world_root_invalid",
                "blank-world roots must be real empty directories",
                details={"root_kind": kind},
            )
        entries = list(path.iterdir())
        if entries:
            raise CutoverEvidenceError(
                "preloaded_science_detected",
                "blank-world roots must be empty before the product path starts",
                details={
                    "root_kind": kind,
                    "entries": sorted(entry.name for entry in entries),
                },
            )


def safe_micu_ledger_snapshot(path: Path) -> dict[str, Any]:
    summary = dict(summarize_live_micu_token_ledger(path))
    summary.pop("path", None)
    summary["ledger_identity_digest"] = canonical_digest(
        {"ledger_path": str(path.resolve())}
    )
    _validate_ledger_snapshot(summary, snapshot_name="snapshot")
    _assert_public_safe(summary, identity="micu_ledger_snapshot")
    return summary


def seal_campaign_decision(
    decision: Mapping[str, object],
    destination: Path,
) -> str:
    normalized = dict(decision)
    if normalized.get("schema_id") != CAMPAIGN_DECISION_SCHEMA_ID:
        raise CutoverEvidenceError(
            "campaign_decision_schema_invalid",
            "campaign decision schema id is not supported",
        )
    declared_digest = normalized.get("decision_digest")
    actual_digest = canonical_digest(
        {key: value for key, value in normalized.items() if key != "decision_digest"}
    )
    if declared_digest != actual_digest:
        raise CutoverEvidenceError(
            "campaign_decision_digest_mismatch",
            "campaign decision digest does not match its canonical payload",
            details={"expected": declared_digest, "actual": actual_digest},
        )
    _write_append_only_bytes(
        destination,
        canonical_json_bytes(normalized) + b"\n",
        error_code="campaign_decision_append_only",
        error_message="campaign decision already exists and cannot be overwritten",
    )
    return actual_digest


def _verify_attempt_bundle_v2_impl(
    bundle_path: Path,
    *,
    artifact_root: Path,
    current_supervision: bool,
) -> VerificationResult:
    issues: list[VerificationIssue] = []
    try:
        bundle_bytes = bundle_path.read_bytes()
        envelope = _strict_json_loads(bundle_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return VerificationResult(
            passed=False,
            bundle_digest=None,
            attempt_id=None,
            attempt_kind=None,
            issues=(
                VerificationIssue(
                    code="bundle_unreadable",
                    identity="bundle",
                    message=f"bundle is not readable canonical JSON: {type(exc).__name__}",
                ),
            ),
        )
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        return VerificationResult(
            passed=False,
            bundle_digest=None,
            attempt_id=None,
            attempt_kind=None,
            issues=(
                VerificationIssue(
                    code="bundle_envelope_invalid",
                    identity="bundle",
                    message="bundle envelope requires payload and bundle_digest",
                ),
            ),
        )
    if set(envelope) != {"payload", "bundle_digest"}:
        issues.append(
            VerificationIssue(
                code="bundle_envelope_invalid",
                identity="bundle",
                message="bundle envelope must contain exactly payload and bundle_digest",
            )
        )
    if bundle_bytes != canonical_json_bytes(envelope) + b"\n":
        issues.append(
            VerificationIssue(
                code="bundle_noncanonical",
                identity="bundle",
                message="bundle bytes are not the canonical UTF-8 JSON serialization",
            )
        )
    payload = dict(envelope["payload"])
    declared_digest = envelope.get("bundle_digest")
    attempt_id = _optional_text(payload.get("attempt_id"))
    attempt_kind = _optional_text(payload.get("attempt_kind"))
    shape_valid = _verify_required_shape(payload, issues)
    try:
        _assert_public_safe(envelope, identity="attempt_bundle_envelope")
    except CutoverEvidenceError as exc:
        issues.append(
            VerificationIssue(
                code=exc.code,
                identity=str(exc.details.get("identity") or "attempt_bundle_envelope"),
                message="bundle envelope contains non-public evidence",
            )
        )
    if shape_valid:
        try:
            artifact_map = _verify_artifacts(
                payload, artifact_root=artifact_root, issues=issues
            )
            _verify_fixed_deliverable_artifact_contracts(
                payload,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_unified_final_deliverables(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_record_digests(payload, issues=issues)
            _verify_lineage(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_aox_operation_dag(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_sequence_join(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_scoring(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            verified_similarity = _verify_similarity(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_product_receipts(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _verify_scientific_outcome(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
                verified_similarity=verified_similarity,
            )
            _verify_fault_injection(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _validate_attempt_semantics(
                payload,
                artifact_root=artifact_root,
                current_supervision=current_supervision,
            )
        except CutoverEvidenceError as exc:
            issues.append(
                VerificationIssue(
                    code=exc.code,
                    identity=str(exc.details.get("identity") or "attempt"),
                    message="attempt semantics are invalid",
                )
            )
        except Exception as exc:
            issues.append(
                VerificationIssue(
                    code="bundle_semantic_validation_failed",
                    identity="attempt",
                    message=f"malformed evidence could not be validated: {type(exc).__name__}",
                )
            )
    actual_digest = canonical_digest(payload)
    if (
        not isinstance(declared_digest, str)
        or _DIGEST_PATTERN.fullmatch(declared_digest) is None
    ):
        issues.append(
            VerificationIssue(
                code="bundle_digest_invalid",
                identity="bundle.bundle_digest",
                message="bundle digest must be a canonical SHA-256 identity",
            )
        )
    if declared_digest != actual_digest:
        issues.append(
            VerificationIssue(
                code="bundle_digest_mismatch",
                identity="bundle.bundle_digest",
                message="canonical attempt bundle digest does not match",
                expected=declared_digest,
                actual=actual_digest,
            )
        )
    return VerificationResult(
        passed=not issues,
        bundle_digest=None if not isinstance(declared_digest, str) else declared_digest,
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        issues=tuple(issues),
    )


def _verify_attempt_bundle_v2(
    bundle_path: Path,
    *,
    artifact_root: Path,
) -> VerificationResult:
    """Run the frozen historical @2 and supervision @1 verification path."""

    return _verify_attempt_bundle_v2_impl(
        bundle_path,
        artifact_root=artifact_root,
        current_supervision=False,
    )


def _verify_attempt_bundle_v2_with_current_supervision(
    bundle_path: Path,
    *,
    artifact_root: Path,
) -> VerificationResult:
    """Reuse @2 payload checks while retaining and validating an exact @3 receipt."""

    return _verify_attempt_bundle_v2_impl(
        bundle_path,
        artifact_root=artifact_root,
        current_supervision=True,
    )


def verify_attempt_bundle(
    bundle_path: Path,
    *,
    artifact_root: Path,
) -> VerificationResult:
    """Dispatch only exact AOX bundle versions; keep the @2 verifier frozen."""

    try:
        envelope = _strict_json_loads(bundle_path.read_text(encoding="utf-8"))
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        schema_id = payload.get("schema_id") if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _verify_attempt_bundle_v2(
            bundle_path,
            artifact_root=artifact_root,
        )
    if schema_id == ATTEMPT_BUNDLE_SCHEMA_ID_V3:
        from .aox_selected_chain_evidence import (
            verify_selected_chain_attempt_bundle,
        )

        return verify_selected_chain_attempt_bundle(
            bundle_path,
            artifact_root=artifact_root,
        )
    if (
        schema_id == ATTEMPT_BUNDLE_SCHEMA_ID_V2
        and isinstance(payload, dict)
        and "scientific_attempt_control" in payload
    ):
        declared_digest = (
            envelope.get("bundle_digest")
            if isinstance(envelope.get("bundle_digest"), str)
            else None
        )
        return VerificationResult(
            passed=False,
            bundle_digest=declared_digest,
            attempt_id=_optional_text(payload.get("attempt_id")),
            attempt_kind=_optional_text(payload.get("attempt_kind")),
            issues=(
                VerificationIssue(
                    code="bundle_version_crossgrade_forbidden",
                    identity="bundle.schema_id",
                    message=(
                        "@3 selected-chain control cannot be relabeled as a "
                        "historical @2 bundle"
                    ),
                ),
            ),
        )
    # @2 and unknown versions both go through the historical verifier.  The
    # latter receives the frozen bundle_schema_invalid result rather than a
    # best-effort parse or implicit upgrade.
    return _verify_attempt_bundle_v2(
        bundle_path,
        artifact_root=artifact_root,
    )


def _report_publish_receipt_is_valid(report: Mapping[str, Any]) -> bool:
    from openzyme_core import is_published_report_link
    from openzyme_core import is_published_report_status

    report_id = str(report.get("report_id") or "")
    session_id = str(report.get("session_id") or "")
    task_id = str(report.get("task_id") or "")
    lane_id = str(report.get("lane_id") or "")
    draft_id = str(report.get("draft_id") or "")
    content_ref = str(report.get("content_ref") or "")
    content_digest = str(report.get("content_digest") or "")
    report_status = str(report.get("status") or "")
    product_report = report.get("product_report_record")
    published_draft = report.get("published_draft_record")
    content_document = report.get("content_document_record")
    publish_events = report.get("publish_events")
    if (
        not isinstance(product_report, dict)
        or not isinstance(published_draft, dict)
        or not isinstance(content_document, dict)
        or not isinstance(publish_events, list)
        or len(publish_events) != 4
        or any(not isinstance(item, dict) for item in publish_events)
    ):
        return False
    document_payload = content_document.get("payload")
    if (
        not isinstance(document_payload, dict)
        or set(document_payload) != {"markdown"}
        or not isinstance(document_payload.get("markdown"), str)
        or not str(document_payload["markdown"]).strip()
    ):
        return False
    markdown_digest = _sha256(str(document_payload["markdown"]).encode("utf-8"))
    event_types = [str(item.get("event_type") or "") for item in publish_events]
    event_cursors = [item.get("cursor") for item in publish_events]
    if (
        event_types
        != [
            "tool.invoked",
            "report_draft.updated",
            "report.generated",
            "tool.completed",
        ]
        or any(
            isinstance(cursor, bool) or not isinstance(cursor, int)
            for cursor in event_cursors
        )
        or event_cursors != sorted(event_cursors)
        or len(set(event_cursors)) != len(event_cursors)
        or any(not str(item.get("event_id") or "") for item in publish_events)
    ):
        return False
    invoked = publish_events[0].get("payload")
    draft_event = publish_events[1].get("payload")
    report_event = publish_events[2].get("payload")
    completed = publish_events[3].get("payload")
    if not all(
        isinstance(item, dict)
        for item in (invoked, draft_event, report_event, completed)
    ):
        return False
    assert isinstance(invoked, dict)
    assert isinstance(draft_event, dict)
    assert isinstance(report_event, dict)
    assert isinstance(completed, dict)
    call_id = str(invoked.get("call_id") or "")
    return (
        bool(report_id)
        and bool(session_id)
        and bool(task_id)
        and bool(lane_id)
        and is_published_report_status(report_status)
        and report.get("invocation_id") in {None, ""}
        and report.get("run_id") in {None, ""}
        and report.get("product_artifact_id") in {None, ""}
        and bool(draft_id)
        and report.get("draft_status") == "published"
        and report.get("published_report_id") == report_id
        and bool(str(report.get("owner_agent_id") or ""))
        and bool(content_ref)
        and report.get("content_document_kind") == "report_draft_content"
        and report.get("content_document_invocation_id") in {None, ""}
        and report.get("content_document_digest") == canonical_digest(content_document)
        and _DIGEST_PATTERN.fullmatch(str(report.get("content_document_digest") or ""))
        is not None
        and content_document.get("document_id") == content_ref
        and content_document.get("session_id") == session_id
        and content_document.get("invocation_id") in {None, ""}
        and content_document.get("document_kind") == "report_draft_content"
        and markdown_digest == content_digest
        and _DIGEST_PATTERN.fullmatch(content_digest) is not None
        and bool(str(report.get("content_artifact_id") or ""))
        and report.get("publication_action") == "report.publish"
        and report.get("cutover_eligible") is True
        and is_published_report_link(
            product_report,
            published_draft,
            task_id=task_id,
        )
        and product_report.get("report_id") == report_id
        and product_report.get("session_id") == session_id
        and product_report.get("task_id") == task_id
        and product_report.get("lane_id") == lane_id
        and product_report.get("invocation_id") in {None, ""}
        and product_report.get("run_id") in {None, ""}
        and product_report.get("artifact_id") in {None, ""}
        and product_report.get("status") == report_status
        and bool(str(product_report.get("created_at") or ""))
        and bool(str(product_report.get("updated_at") or ""))
        and published_draft.get("draft_id") == draft_id
        and published_draft.get("session_id") == session_id
        and published_draft.get("task_id") == task_id
        and published_draft.get("owner_agent_id") == report.get("owner_agent_id")
        and published_draft.get("status") == "published"
        and published_draft.get("content_ref") == content_ref
        and published_draft.get("published_report_id") == report_id
        and bool(str(published_draft.get("created_at") or ""))
        and bool(str(published_draft.get("updated_at") or ""))
        and bool(call_id)
        and invoked.get("tool_name") == "report.publish"
        and invoked.get("task_id") == task_id
        and invoked.get("lane_id") == lane_id
        and invoked.get("role") == "reporter"
        and draft_event == published_draft
        and report_event == product_report
        and completed.get("call_id") == call_id
        and completed.get("tool_name") == "report.publish"
        and completed.get("task_id") == task_id
        and completed.get("lane_id") == lane_id
        and completed.get("role") == "reporter"
        and completed.get("ok") is True
    )


def evaluate_campaign(
    records: Sequence[AttemptRunRecord],
    *,
    decided_at: str | None = None,
) -> dict[str, Any]:
    from .aox_public_conductor_bundle import PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID

    if any(
        _read_bundle_payload(record.bundle_path).get("bundle_profile")
        == PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID
        for record in records
    ):
        from .aox_public_conductor_bundle import (
            evaluate_public_conductor_campaign,
        )

        return evaluate_public_conductor_campaign(
            records,
            decided_at=decided_at,
        )
    blockers: list[dict[str, str]] = []
    expected_kinds = ("positive", "positive", "fault")
    payloads: list[dict[str, Any] | None] = []
    for index, record in enumerate(records):
        current_verification = verify_attempt_bundle(
            record.bundle_path,
            artifact_root=record.artifact_root,
        )
        if not current_verification.passed:
            issue = (
                current_verification.issues[0] if current_verification.issues else None
            )
            blockers.append(
                {
                    "code": "attempt_verification_failed",
                    "identity": record.attempt_id,
                    "message": "offline verification failed"
                    if issue is None
                    else f"{issue.code}: {issue.identity}",
                }
            )
            payloads.append(None)
        elif (
            not record.verification.passed
            or current_verification.attempt_id != record.attempt_id
            or current_verification.attempt_kind != record.attempt_kind
            or current_verification.bundle_digest != record.bundle_digest
            or record.verification.attempt_id != current_verification.attempt_id
            or record.verification.attempt_kind != current_verification.attempt_kind
            or record.verification.bundle_digest != current_verification.bundle_digest
        ):
            blockers.append(
                {
                    "code": "campaign_record_binding_mismatch",
                    "identity": record.attempt_id,
                    "message": "campaign record differs from its offline verification identity",
                }
            )
            payloads.append(None)
        else:
            payload = _read_bundle_payload(record.bundle_path)
            identity = payload.get("identity")
            if (
                payload.get("attempt_id") != record.attempt_id
                or payload.get("attempt_kind") != record.attempt_kind
                or not isinstance(identity, dict)
                or not identity
                or canonical_digest(payload) != record.bundle_digest
            ):
                blockers.append(
                    {
                        "code": "campaign_bundle_binding_mismatch",
                        "identity": f"campaign.attempts[{index}]",
                        "message": "campaign record is not bound to its sealed bundle payload",
                    }
                )
                payloads.append(None)
            else:
                payloads.append(payload)
        if index < len(expected_kinds):
            expected_kind = expected_kinds[index]
            if record.attempt_kind != expected_kind:
                blockers.append(
                    {
                        "code": "campaign_attempt_order",
                        "identity": f"campaign.attempts[{index}]",
                        "message": f"expected {expected_kind}, got {record.attempt_kind}",
                    }
                )

    complete_payloads = [payload for payload in payloads if payload is not None]
    if complete_payloads and len(complete_payloads) == len(payloads):
        identity_digests = {
            str(dict(payload["identity"]).get("identity_digest") or "")
            for payload in complete_payloads
        }
        if len(identity_digests) != 1 or "" in identity_digests:
            blockers.append(
                {
                    "code": "campaign_identity_drift",
                    "identity": "campaign.identity",
                    "message": "all attempts must pin one commit/config/workflow/scoring/image/SDK identity",
                }
            )
        root_identities = [
            str(dict(payload["clean_world"]).get("root_identity") or "")
            for payload in complete_payloads
        ]
        if len(root_identities) != len(set(root_identities)) or "" in root_identities:
            blockers.append(
                {
                    "code": "campaign_roots_not_independent",
                    "identity": "campaign.clean_roots",
                    "message": "every attempt must use a distinct proved clean root",
                }
            )
        ledger_snapshots = [
            dict(payload["micu_ledger"]) for payload in complete_payloads
        ]
        for index in range(len(ledger_snapshots) - 1):
            if dict(ledger_snapshots[index].get("after") or {}) != dict(
                ledger_snapshots[index + 1].get("before") or {}
            ):
                blockers.append(
                    {
                        "code": "campaign_micu_ledger_discontinuity",
                        "identity": f"campaign.attempts[{index}:{index + 2}]",
                        "message": "MICU snapshots are not one continuous cumulative ledger",
                    }
                )
                break
    positive_payloads = [payload for payload in payloads[:2] if payload is not None]
    if len(positive_payloads) == 2:
        _append_independence_blockers(positive_payloads, blockers=blockers)
    for index, payload in enumerate(payloads[:2]):
        if payload is None:
            continue
        outcome = dict(payload["scientific_outcome"])
        report = dict(payload["report"])
        if outcome.get("cutover_eligible") is not True:
            blockers.append(
                {
                    "code": str(
                        outcome.get("failure_code") or "positive_not_cutover_eligible"
                    ),
                    "identity": f"attempt[{index + 1}].scientific_outcome",
                    "message": "positive attempt is not cutover eligible",
                }
            )
        if not _report_publish_receipt_is_valid(report):
            blockers.append(
                {
                    "code": "positive_report_not_published",
                    "identity": f"attempt[{index + 1}].report",
                    "message": (
                        "positive attempt requires one ready report backed by the "
                        "published draft and its sealed content document"
                    ),
                }
            )
    if len(records) != 3:
        blockers.append(
            {
                "code": "campaign_attempt_count",
                "identity": "campaign.attempts",
                "message": "campaign requires exactly two positive attempts followed by one fault attempt",
            }
        )
    if len(payloads) >= 3 and payloads[2] is not None:
        fault_payload = payloads[2]
        assert fault_payload is not None
        raw_fault = fault_payload.get("fault_injection")
        fault = dict(raw_fault) if isinstance(raw_fault, dict) else {}
        outcome = dict(fault_payload["scientific_outcome"])
        report = dict(fault_payload["report"])
        if (
            fault.get("fault_id") != FAULT_ARTIFACT_BYTE_FLIP_ID
            or fault.get("reached_target_seam") is not True
            or fault.get("expected_failure_observed") is not True
            or outcome.get("cutover_eligible") is not False
            or report.get("cutover_eligible") is not False
        ):
            blockers.append(
                {
                    "code": "fault_not_fail_closed",
                    "identity": "attempt[3].fault_injection",
                    "message": "controlled fault did not prove terminal fail-closed behavior",
                }
            )
    if len(payloads) >= 2 and all(payload is not None for payload in payloads[:2]):
        first_launch = dict(
            dict(payloads[0].get("product_path") or {}).get("launch_receipt") or {}
        )
        second_launch = dict(
            dict(payloads[1].get("product_path") or {}).get("launch_receipt") or {}
        )
        if (
            first_launch.get("approval_mode") != "chrome-once"
            or first_launch.get("campaign_attempt_number") != 1
            or not isinstance(first_launch.get("browser_approval_receipt"), dict)
            or not isinstance(first_launch.get("browser_observation_receipt"), dict)
            or second_launch.get("approval_mode") != "chrome-once"
            or second_launch.get("campaign_attempt_number") != 2
            or second_launch.get("browser_approval_receipt") is not None
            or second_launch.get("browser_observation_receipt") is not None
        ):
            blockers.append(
                {
                    "code": "campaign_chrome_proof_missing",
                    "identity": "campaign.attempts[0].browser_approval_receipt",
                    "message": "campaign requires Chrome-observed approval on positive attempt one",
                }
            )
    if len(payloads) >= 3 and payloads[2] is not None:
        fault_launch = dict(
            dict(payloads[2].get("product_path") or {}).get("launch_receipt") or {}
        )
        if (
            fault_launch.get("approval_mode") != "chrome-once"
            or fault_launch.get("campaign_attempt_number") != 3
            or fault_launch.get("browser_approval_receipt") is not None
            or fault_launch.get("browser_observation_receipt") is not None
        ):
            blockers.append(
                {
                    "code": "campaign_fault_launch_attestation_invalid",
                    "identity": "campaign.attempts[2].launch_receipt",
                    "message": "fault attempt must retain the campaign launch mode as attempt three",
                }
            )
    blocker = blockers[0] if blockers else None
    decision_payload = {
        "schema_id": CAMPAIGN_DECISION_SCHEMA_ID,
        "decided_at": decided_at or datetime.now(UTC).isoformat(),
        "decision": "GO" if blocker is None else "NO-GO",
        "attempt_digests": [record.bundle_digest for record in records],
        "attempt_ids": [record.attempt_id for record in records],
        "blocker": blocker,
    }
    return {
        **decision_payload,
        "decision_digest": canonical_digest(decision_payload),
    }


def _append_independence_blockers(
    payloads: Sequence[Mapping[str, Any]],
    *,
    blockers: list[dict[str, str]],
) -> None:
    scalar_extractors = {
        "session_id": lambda payload: dict(payload.get("product_path") or {}).get(
            "session_id"
        ),
        "entry_message_id": lambda payload: dict(payload.get("product_path") or {}).get(
            "entry_message_id"
        ),
        "final_master_response_id": lambda payload: dict(
            payload.get("product_path") or {}
        ).get("final_master_response_id"),
        "workspace_projection_digest": lambda payload: dict(
            payload.get("product_path") or {}
        ).get("workspace_projection_digest"),
        "event_log_digest": lambda payload: dict(payload.get("product_path") or {}).get(
            "event_log_digest"
        ),
        "hpc_workspace_label": lambda payload: dict(
            payload.get("clean_world") or {}
        ).get("hpc_workspace_label"),
    }
    for identity, extractor in scalar_extractors.items():
        values = [str(extractor(payload) or "") for payload in payloads]
        if "" in values or len(values) != len(set(values)):
            blockers.append(
                {
                    "code": "campaign_positive_not_independent",
                    "identity": f"campaign.independence.{identity}",
                    "message": f"positive attempts must use distinct {identity} receipts",
                }
            )
            return
    set_extractors = {
        "task_ids": lambda payload: {
            str(item.get("task_id") or "")
            for item in payload.get("tasks") or []
            if isinstance(item, dict)
        },
        "operation_ids": lambda payload: {
            str(item.get("operation_id") or "")
            for item in payload.get("operations") or []
            if isinstance(item, dict)
        },
        "provider_invocations": lambda payload: {
            str(item.get("invocation_id") or "")
            for item in payload.get("provider_identities") or []
            if isinstance(item, dict)
        },
        "toolchain_jobs": lambda payload: {
            str(item.get("job_id") or "")
            for item in payload.get("toolchain_identities") or []
            if isinstance(item, dict)
        },
        "hpc_workspace_ids": lambda payload: {
            str(item)
            for item in dict(
                dict(payload.get("product_path") or {}).get("hpc_workspace_binding")
                or {}
            ).get("workspace_ids")
            or []
        },
    }
    for identity, extractor in set_extractors.items():
        left, right = (extractor(payload) - {""} for payload in payloads)
        if not left or not right or left & right:
            blockers.append(
                {
                    "code": "campaign_positive_not_independent",
                    "identity": f"campaign.independence.{identity}",
                    "message": f"positive attempts must use disjoint {identity} receipts",
                }
            )
            return


def _normalize_identity(identity: Mapping[str, object]) -> dict[str, str]:
    actual_keys = set(identity)
    if actual_keys != set(_IDENTITY_FIELDS):
        raise CutoverEvidenceError(
            "campaign_identity_schema_invalid",
            "campaign identity must contain exactly the seven cutover identity fields",
            details={
                "missing": sorted(set(_IDENTITY_FIELDS) - actual_keys),
                "extra": sorted(
                    str(key) for key in actual_keys - set(_IDENTITY_FIELDS)
                ),
            },
        )
    normalized = {key: str(identity.get(key) or "").strip() for key in _IDENTITY_FIELDS}
    missing = [key for key, value in normalized.items() if not value]
    if missing:
        raise CutoverEvidenceError(
            "campaign_identity_missing",
            "campaign identity is incomplete",
            details={"missing": missing},
        )
    for key in _IDENTITY_DIGEST_FIELDS:
        if _DIGEST_PATTERN.fullmatch(normalized[key]) is None:
            raise CutoverEvidenceError(
                "campaign_identity_digest_invalid",
                "campaign identity digest is malformed",
                details={"identity": f"identity.{key}"},
            )
    if re.fullmatch(r"[0-9a-f]{40}", normalized["git_commit"]) is None:
        raise CutoverEvidenceError(
            "campaign_git_commit_invalid",
            "campaign git identity must be a full lowercase commit id",
            details={"identity": "identity.git_commit"},
        )
    if (
        re.fullmatch(
            r"workflow:[a-z0-9][a-z0-9._-]*@[0-9]+\.[0-9]+\.[0-9]+#sha256:[0-9a-f]{64}",
            normalized["workflow_ref"],
        )
        is None
    ):
        raise CutoverEvidenceError(
            "campaign_workflow_ref_invalid",
            "campaign workflow ref must be a full digest-pinned selection ref",
            details={"identity": "identity.workflow_ref"},
        )
    return normalized


def _validate_clean_world_proof(payload: Mapping[str, Any]) -> None:
    clean_world = dict(payload.get("clean_world") or {})
    schema_id = clean_world.get("schema_id")
    legacy = schema_id == _LEGACY_BLANK_WORLD_ROOT_PROOF_SCHEMA_ID
    expected_root_names = {
        "artifact": "artifacts",
        "blob": "blobs",
        "sandbox": "sandboxes",
        "hpc": "hpc-workspace",
        "evidence": "evidence",
    }
    expected_initial_entries = {
        "sqlite": 0,
        **{root_kind: 0 for root_kind in expected_root_names},
    }
    bundle_identity = dict(payload.get("identity") or {})
    prerequisites = normalize_aox_cutover_prerequisites(
        dict(clean_world.get("allowed_prerequisites") or {}),
        identity={key: bundle_identity.get(key) for key in _IDENTITY_FIELDS},
    )
    architecture_qualification_value = clean_world.get("architecture_qualification")
    if not isinstance(architecture_qualification_value, Mapping):
        raise CutoverEvidenceError(
            "aox_architecture_qualification_receipt_invalid",
            "blank-world proof lacks architecture qualification",
            details={"identity": "clean_world.architecture_qualification"},
        )
    architecture_qualification = _normalize_architecture_qualification(
        architecture_qualification_value,
        expected_source_commit=str(bundle_identity.get("git_commit") or ""),
    )
    if (
        set(clean_world)
        != (
            _LEGACY_BLANK_WORLD_ROOT_PROOF_KEYS
            if legacy
            else _BLANK_WORLD_ROOT_PROOF_KEYS
        )
        or schema_id
        not in {
            BLANK_WORLD_ROOT_PROOF_SCHEMA_ID,
            _LEGACY_BLANK_WORLD_ROOT_PROOF_SCHEMA_ID,
        }
        or clean_world.get("architecture_qualification") != architecture_qualification
        or (
            legacy
            and clean_world.get("attempt_id") != payload.get("attempt_id")
        )
        or (
            not legacy
            and re.fullmatch(
                r"formal-slot-[a-f0-9]{24}",
                str(clean_world.get("launch_id") or ""),
            )
            is None
        )
        or clean_world.get("attempt_kind") != payload.get("attempt_kind")
        or clean_world.get("root_names") != expected_root_names
        or clean_world.get("initial_entries") != expected_initial_entries
        or clean_world.get("provider_cache_mode") != "bypass"
        or clean_world.get("evidence_cache_reuse") is not False
        or clean_world.get("sqlite_preexisting") is not False
        or clean_world.get("allowed_prerequisite_digest")
        != canonical_digest(prerequisites)
        or not _DIGEST_PATTERN.fullmatch(str(clean_world.get("root_identity") or ""))
        or _ATTEMPT_ID_PATTERN.fullmatch(
            str(clean_world.get("hpc_workspace_label") or "")
        )
        is None
    ):
        raise CutoverEvidenceError(
            "blank_world_proof_invalid",
            "attempt does not carry a complete self-consistent clean-root proof",
            details={"identity": "clean_world"},
        )


def _validate_architecture_qualification_evidence(
    payload: Mapping[str, Any],
) -> None:
    identity = dict(payload.get("identity") or {})
    clean_world = dict(payload.get("clean_world") or {})
    product_path = dict(payload.get("product_path") or {})
    launch_receipt = dict(product_path.get("launch_receipt") or {})
    clean_value = clean_world.get("architecture_qualification")
    launch_value = launch_receipt.get("architecture_qualification")
    if not isinstance(clean_value, Mapping) or not isinstance(launch_value, Mapping):
        raise CutoverEvidenceError(
            "aox_architecture_qualification_receipt_missing",
            "attempt evidence lacks the launch-bound architecture qualification receipt",
            details={
                "identity": "product_path.launch_receipt.architecture_qualification"
            },
        )
    clean_receipt = _normalize_architecture_qualification(
        clean_value,
        expected_source_commit=str(identity.get("git_commit") or ""),
    )
    launch_qualification = _normalize_architecture_qualification(
        launch_value,
        expected_source_commit=str(identity.get("git_commit") or ""),
    )
    if (
        launch_receipt.get("schema_id") != AOX_LAUNCH_RECEIPT_SCHEMA_ID
        or launch_qualification != clean_receipt
    ):
        raise CutoverEvidenceError(
            "aox_architecture_qualification_receipt_mismatch",
            "attempt launch receipt does not match its blank-world qualification proof",
            details={
                "identity": "product_path.launch_receipt.architecture_qualification"
            },
        )


def _validate_effective_config_attestation(payload: Mapping[str, Any]) -> None:
    identity = dict(payload.get("identity") or {})
    product_path = dict(payload.get("product_path") or {})
    launch_receipt = dict(product_path.get("launch_receipt") or {})
    config_value = launch_receipt.get("effective_config")
    if not isinstance(config_value, dict):
        raise CutoverEvidenceError(
            "effective_config_attestation_missing",
            "cutover evidence lacks the canonical effective-config preimage",
            details={"identity": "product_path.launch_receipt.effective_config"},
        )
    try:
        config = normalize_aox_blank_world_runtime_config(
            config_value,
            expected_runner_contracts=AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
        )
    except AoxRuntimeConfigSchemaError as exc:
        raise CutoverEvidenceError(
            "effective_config_attestation_invalid",
            "sealed effective configuration violates its closed schema",
            details=exc.details(),
        ) from exc
    if canonical_json_bytes(config_value) != canonical_json_bytes(config):
        raise CutoverEvidenceError(
            "effective_config_attestation_invalid",
            "sealed effective configuration is not in canonical normalized form",
            details={"identity": "product_path.launch_receipt.effective_config"},
        )
    # Observer-era @3 remains read-only verifiable with its sealed @3 runtime
    # preimage. Current @4 production bundles dispatch to the public-conductor
    # verifier before reaching this historical compatibility path.
    if (
        payload.get("schema_id") == ATTEMPT_BUNDLE_SCHEMA_ID_V3
        and payload.get("bundle_profile") is None
        and config.get("schema_id") != AOX_BLANK_WORLD_RUNTIME_CONFIG_V3_SCHEMA_ID
    ):
        raise CutoverEvidenceError(
            "effective_config_attestation_invalid",
            "observer-era @3 evidence requires its exact historical @3 config",
            details={"identity": "product_path.launch_receipt.effective_config"},
        )
    config_digest = canonical_digest(config)
    research = dict(config["research"])
    driver = dict(config["driver"])
    clean_world = dict(payload.get("clean_world") or {})
    prerequisites = dict(clean_world.get("allowed_prerequisites") or {})
    micu_before = dict(dict(payload.get("micu_ledger") or {}).get("before") or {})
    credential_slots = dict(research.get("credential_slots") or {})
    approval_mode = str(launch_receipt.get("approval_mode") or "")
    runner_contract_expectations = _runner_contract_expectations_from_config(config)
    if (
        config_digest != identity.get("config_digest")
        or launch_receipt.get("effective_config_digest") != config_digest
        or product_path.get("runtime_config_digest") != config_digest
        or research.get("ncbi_identity_digest") != prerequisites.get("ncbi_identity")
        or credential_slots != prerequisites.get("credential_slots")
        or driver.get("micu_ledger_identity_digest")
        != micu_before.get("ledger_identity_digest")
        or driver.get("approval_mode") != approval_mode
    ):
        raise CutoverEvidenceError(
            "effective_config_attestation_invalid",
            "sealed effective configuration does not reproduce the launch identity and cutover constraints",
            details={"identity": "product_path.launch_receipt.effective_config"},
        )
    if not runner_contract_expectations:
        raise CutoverEvidenceError(
            "effective_config_runner_contracts_invalid",
            "sealed effective configuration lacks exact AOX runner-contract expectations",
            details={
                "identity": "effective_config.execution.aox_runner_contract_expectations"
            },
        )


def _runner_contract_expectations_from_config(
    config: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    execution = dict(config.get("execution") or {})
    raw_expectations = execution.get("aox_runner_contract_expectations")
    if not isinstance(raw_expectations, dict):
        return {}
    expectations = dict(raw_expectations)
    raw_contracts = expectations.get("contracts")
    expected_by_tool_id = {
        contract["tool_id"]: contract
        for contract in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.values()
    }
    if (
        set(expectations) != {"schema_id", "manifest_digest", "contracts"}
        or expectations.get("schema_id") != "aox_runner_contract_expectations@1"
        or _DIGEST_PATTERN.fullmatch(str(expectations.get("manifest_digest") or ""))
        is None
        or not isinstance(raw_contracts, dict)
        or set(raw_contracts) != set(expected_by_tool_id)
    ):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for tool_id, expected in expected_by_tool_id.items():
        raw = raw_contracts.get(tool_id)
        if not isinstance(raw, dict) or set(raw) != {
            "adapter_id",
            "command_template_id",
            "runner_contract_digest",
        }:
            return {}
        contract = {key: str(value) for key, value in raw.items()}
        if (
            contract["adapter_id"] != expected["adapter_id"]
            or contract["command_template_id"] != expected["command_template_id"]
            or _DIGEST_PATTERN.fullmatch(contract["runner_contract_digest"]) is None
        ):
            return {}
        normalized[tool_id] = contract
    return normalized


def _artifact_seals_provider_response(
    artifact_root: Path,
    artifact: Mapping[str, Any],
    *,
    response_digest: str,
) -> bool:
    try:
        content = _resolve_artifact_path(
            artifact_root,
            str(artifact.get("relative_path") or ""),
        ).read_bytes()
    except (CutoverEvidenceError, OSError):
        return False
    return artifact.get(
        "content_digest"
    ) == response_digest or _provider_response_bytes_contain_digest(
        content, response_digest
    )


def _provider_response_bytes_contain_digest(
    content: bytes,
    response_digest: object,
) -> bool:
    if _sha256(content) == response_digest:
        return True
    try:
        payload = _strict_json_loads(content.decode("utf-8"))
    except (CutoverEvidenceError, UnicodeDecodeError, ValueError):
        return False
    if (
        not isinstance(payload, dict)
        or payload.get("schema_id") != "provider_raw_http_response_set@1"
        or not isinstance(payload.get("responses"), list)
        or not payload["responses"]
    ):
        return False
    response_digest_matched = False
    for record in payload["responses"]:
        if not isinstance(record, dict):
            return False
        try:
            raw = base64.b64decode(str(record.get("body_base64") or ""), validate=True)
        except ValueError:
            return False
        actual_digest = _sha256(raw)
        if (
            record.get("body_encoding") != "base64"
            or record.get("size_bytes") != len(raw)
            or record.get("body_digest") != actual_digest
        ):
            return False
        if actual_digest == response_digest:
            response_digest_matched = True
    return response_digest_matched


def _artifact_seals_upstream_empty_receipt(
    artifact_root: Path,
    artifact: Mapping[str, Any],
    *,
    provider: Mapping[str, Any],
    dependency: Mapping[str, Any],
) -> bool:
    try:
        content = _resolve_artifact_path(
            artifact_root,
            str(artifact.get("relative_path") or ""),
        ).read_bytes()
        payload = _strict_json_loads(content.decode("utf-8"))
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    expected_keys = {
        "schema_id",
        "provider_record_id",
        "provider",
        "status",
        "canonical_ref_kind",
        "operation_id",
        "invocation_id",
        "provider_io_performed",
        "cache_consulted",
        "reason",
        "upstream_provider_record_id",
        "derivation_operation_id",
        "derived_accession_artifact_id",
        "derived_accession_artifact_digest",
        "derived_accessions_digest",
        "decision_input_digest",
        "skip_receipt_digest",
    }
    decision_material = {
        "reason": payload.get("reason"),
        "upstream_provider_record_id": payload.get("upstream_provider_record_id"),
        "derivation_operation_id": payload.get("derivation_operation_id"),
        "derived_accession_artifact_id": payload.get("derived_accession_artifact_id"),
        "derived_accession_artifact_digest": payload.get(
            "derived_accession_artifact_digest"
        ),
        "derived_accessions_digest": payload.get("derived_accessions_digest"),
    }
    expected_skip_digest = canonical_digest(
        {key: value for key, value in payload.items() if key != "skip_receipt_digest"}
    )
    return (
        set(payload) == expected_keys
        and payload.get("schema_id") == "provider_upstream_empty_receipt@1"
        and payload.get("provider_record_id") == provider.get("provider_record_id")
        and payload.get("provider") == "uniprot"
        and payload.get("status") == "upstream_empty"
        and payload.get("canonical_ref_kind") == "upstream_empty"
        and payload.get("operation_id") is None
        and payload.get("invocation_id") is None
        and payload.get("provider_io_performed") is False
        and payload.get("cache_consulted") is False
        and payload.get("reason") in {"no_hmmer_hits", "no_filtered_hmmer_accessions"}
        and payload.get("reason") == dependency.get("terminal_empty_reason")
        and payload.get("upstream_provider_record_id")
        == dependency.get("upstream_provider_record_id")
        and payload.get("derivation_operation_id")
        == dependency.get("derivation_operation_id")
        and payload.get("derived_accession_artifact_id")
        == dependency.get("derived_accession_artifact_id")
        and payload.get("derived_accession_artifact_digest")
        == dependency.get("derived_accession_artifact_digest")
        and payload.get("derived_accessions_digest") == canonical_digest([])
        and payload.get("decision_input_digest") == canonical_digest(decision_material)
        and payload.get("skip_receipt_digest") == expected_skip_digest
        and provider.get("skip_receipt_digest") == expected_skip_digest
        and dependency.get("skip_receipt_digest") == expected_skip_digest
        and dependency.get("skip_artifact_id") == artifact.get("artifact_id")
        and provider.get("artifact_ids") == [artifact.get("artifact_id")]
        and artifact.get("scope") == "formal"
        and artifact.get("origin") == "attestation"
        and artifact.get("content_digest") == _sha256(content)
    )


def _hmmer_upstream_empty_is_proven(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
) -> bool:
    try:
        from openzyme_pipeline import aox_hmmer

        outcome = dict(payload.get("scientific_outcome") or {})
        chain = dict(
            dict(payload.get("scientific_checks") or {}).get("aox_chain") or {}
        )
        empty_branch = dict(chain.get("empty_branch") or {})
        operation_roles = dict(chain.get("operation_roles") or {})
        artifact_roles = dict(chain.get("artifact_roles") or {})
        dependencies = chain.get("provider_dependencies")
        if not isinstance(dependencies, list) or len(dependencies) != 1:
            return False
        dependency = dict(dependencies[0])
        artifacts = {
            str(item.get("artifact_id") or ""): dict(item)
            for item in payload.get("artifacts") or []
            if isinstance(item, dict)
        }
        operations = {
            str(item.get("operation_id") or ""): dict(item)
            for item in payload.get("operations") or []
            if isinstance(item, dict)
        }
        providers = {
            str(item.get("provider_record_id") or ""): dict(item)
            for item in payload.get("provider_identities") or []
            if isinstance(item, dict)
        }
        parsed_id = str(dependency.get("parsed_hit_artifact_id") or "")
        derived_id = str(dependency.get("derived_accession_artifact_id") or "")
        skip_id = str(dependency.get("skip_artifact_id") or "")
        parsed_artifact = artifacts.get(parsed_id)
        derived_artifact = artifacts.get(derived_id)
        skip_artifact = artifacts.get(skip_id)
        derivation_id = str(dependency.get("derivation_operation_id") or "")
        derivation_operation = operations.get(derivation_id)
        upstream_provider = providers.get(
            str(dependency.get("upstream_provider_record_id") or "")
        )
        downstream_provider = providers.get(
            str(dependency.get("downstream_provider_record_id") or "")
        )
        if any(
            item is None
            for item in (
                parsed_artifact,
                derived_artifact,
                skip_artifact,
                derivation_operation,
                upstream_provider,
                downstream_provider,
            )
        ):
            return False
        assert parsed_artifact is not None
        assert derived_artifact is not None
        assert skip_artifact is not None
        assert derivation_operation is not None
        assert upstream_provider is not None
        assert downstream_provider is not None
        parsed_bytes = _resolve_artifact_path(
            artifact_root,
            str(parsed_artifact.get("relative_path") or ""),
        ).read_bytes()
        derived_bytes = _resolve_artifact_path(
            artifact_root,
            str(derived_artifact.get("relative_path") or ""),
        ).read_bytes()
        result = aox_hmmer.parse_and_filter_csv(
            parsed_bytes,
            expected_contract_id=aox_hmmer.CONTRACT_ID,
            expected_contract_digest=aox_hmmer.CONTRACT_DIGEST,
            expected_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
            expected_input_digest=str(parsed_artifact.get("content_digest") or ""),
        )
        upstream_response_ids = [
            str(item) for item in dependency.get("upstream_response_artifact_ids") or []
        ]
        upstream_artifact_ids = {
            str(item) for item in upstream_provider.get("artifact_ids") or []
        }
        raw_response_body_digests: set[str] = set()
        for artifact_id in upstream_response_ids:
            response_artifact = artifacts.get(artifact_id)
            if response_artifact is None:
                return False
            raw_envelope = _strict_json_loads(
                _resolve_artifact_path(
                    artifact_root,
                    str(response_artifact.get("relative_path") or ""),
                ).read_text(encoding="utf-8")
            )
            if (
                not isinstance(raw_envelope, dict)
                or raw_envelope.get("schema_id") != "provider_raw_http_response_set@1"
                or raw_envelope.get("provider") != "ebi_hmmer"
            ):
                return False
            for response in raw_envelope.get("responses") or []:
                if not isinstance(response, dict):
                    return False
                body = base64.b64decode(
                    str(response.get("body_base64") or ""),
                    validate=True,
                )
                body_digest = _sha256(body)
                if (
                    response.get("body_encoding") != "base64"
                    or response.get("body_digest") != body_digest
                    or response.get("size_bytes") != len(body)
                ):
                    return False
                raw_response_body_digests.add(body_digest)
        reason = (
            "no_hmmer_hits"
            if result.input_row_count == 0
            else "no_filtered_hmmer_accessions"
        )
        input_refs = [
            dict(item)
            for item in derivation_operation.get("inputs") or []
            if isinstance(item, dict)
        ]
        output_refs = [
            dict(item)
            for item in derivation_operation.get("outputs") or []
            if isinstance(item, dict)
        ]
        derivation_identity = dict(
            derivation_operation.get("operation_identity_material") or {}
        )
        empty_materialization_id = str(
            empty_branch.get("empty_materialization_operation_id") or ""
        )
        empty_membership_id = str(
            empty_branch.get("empty_membership_operation_id") or ""
        )
        empty_scoring_id = str(
            operation_roles.get("empty_target_scoring_materialization") or ""
        )
        empty_materialization = operations.get(empty_materialization_id)
        empty_membership = operations.get(empty_membership_id)
        empty_scoring = operations.get(empty_scoring_id)
        empty_materialization_identity = dict(
            (empty_materialization or {}).get("operation_identity_material") or {}
        )
        empty_membership_identity = dict(
            (empty_membership or {}).get("operation_identity_material") or {}
        )
        empty_scoring_identity = dict(
            (empty_scoring or {}).get("operation_identity_material") or {}
        )

        def operation_refs(
            operation: Mapping[str, Any] | None, direction: str
        ) -> dict[str, str]:
            return {
                str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
                for ref in (operation or {}).get(direction) or []
                if isinstance(ref, dict)
            }

        def expected_refs(*roles: str) -> dict[str, str]:
            result_refs: dict[str, str] = {}
            for role in roles:
                artifact_id = str(artifact_roles.get(role) or "")
                artifact = artifacts.get(artifact_id)
                if artifact is None:
                    return {}
                result_refs[artifact_id] = str(artifact.get("content_digest") or "")
            return result_refs

        return (
            outcome.get("status") == "empty"
            and outcome.get("candidate_count") == 0
            and outcome.get("empty_result_reason") == reason
            and empty_branch.get("schema_id") == "aox_empty_branch@1"
            and empty_branch.get("stage") == _HMMER_UPSTREAM_EMPTY_STAGE
            and empty_branch.get("reason") == reason
            and empty_branch.get("trigger_artifact_id") == derived_id
            and empty_branch.get("trigger_artifact_digest")
            == derived_artifact.get("content_digest")
            and empty_branch.get("observed_count_before") == result.input_row_count
            and empty_branch.get("observed_count_after") == 0
            and empty_branch.get("derivation_operation_id") == derivation_id
            and empty_branch.get("skip_provider_record_id")
            == downstream_provider.get("provider_record_id")
            and empty_branch.get("omitted_controlled_roles")
            == ["uniprot_fetch", "candidate_alignment", "cdhit"]
            and bool(empty_branch.get("empty_materialization_operation_id"))
            and bool(empty_branch.get("empty_membership_operation_id"))
            and operation_roles.get("upstream_empty_materialization")
            == empty_materialization_id
            and operation_roles.get("empty_membership") == empty_membership_id
            and bool(empty_scoring_id)
            and empty_materialization_identity.get("calculation_id")
            == "aox_upstream_empty_materialization@1"
            and empty_membership_identity.get("calculation_id")
            == aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID
            and empty_scoring_identity.get("calculation_id")
            == "aox_reference_only_scoring_alignment@1"
            and operation_refs(empty_materialization, "inputs")
            == expected_refs("hmmer_score_filtered_accessions")
            and operation_refs(empty_materialization, "outputs")
            == expected_refs("post_uniprot_filtered_hits", "target_sequences")
            and operation_refs(empty_scoring, "inputs")
            == expected_refs("scoring_input", "target_sequences")
            and operation_refs(empty_scoring, "outputs")
            == expected_refs("scoring_alignment")
            and dependency.get("derivation_id") == aox_hmmer.CONTRACT_ID
            and dependency.get("derivation_contract_digest")
            == aox_hmmer.CONTRACT_DIGEST
            and dependency.get("derivation_implementation_digest")
            == aox_hmmer.IMPLEMENTATION_DIGEST
            and dependency.get("derived_accessions") == []
            and dependency.get("derived_accessions_digest") == canonical_digest([])
            and dependency.get("terminal_empty_reason") == reason
            and derived_bytes == result.to_csv().encode("utf-8")
            and derived_artifact.get("content_digest") == _sha256(derived_bytes)
            and dependency.get("parsed_hit_artifact_digest")
            == parsed_artifact.get("content_digest")
            and parsed_id in upstream_artifact_ids
            and bool(upstream_response_ids)
            and len(upstream_response_ids) == len(set(upstream_response_ids))
            and set(upstream_response_ids).issubset(upstream_artifact_ids)
            and bool(raw_response_body_digests)
            and all(
                hit.raw_page_digest in raw_response_body_digests for hit in result.hits
            )
            and artifact_roles.get("hmmer_parsed_hits") == parsed_id
            and artifact_roles.get("hmmer_score_filtered_accessions") == derived_id
            and operation_roles.get("pre_uniprot_score_filter") == derivation_id
            and not {
                "uniprot_fetch",
                "candidate_alignment",
                "cdhit",
                "post_uniprot_filter",
            }.intersection(operation_roles)
            and derivation_operation.get("canonical_ref_kind") == "sandbox_calculation"
            and derivation_identity.get("calculation_id") == aox_hmmer.CONTRACT_ID
            and derivation_identity.get("calculation_contract_digest")
            == aox_hmmer.CONTRACT_DIGEST
            and derivation_identity.get("calculation_implementation_digest")
            == aox_hmmer.IMPLEMENTATION_DIGEST
            and input_refs
            == [
                {
                    "artifact_id": parsed_id,
                    "content_digest": parsed_artifact.get("content_digest"),
                }
            ]
            and output_refs
            == [
                {
                    "artifact_id": derived_id,
                    "content_digest": derived_artifact.get("content_digest"),
                }
            ]
            and upstream_provider.get("provider") == "ebi_hmmer"
            and downstream_provider.get("provider") == "uniprot"
            and downstream_provider.get("canonical_ref_kind") == "upstream_empty"
            and downstream_provider.get("status") == "upstream_empty"
            and downstream_provider.get("operation_id") in {None, ""}
            and downstream_provider.get("invocation_id") in {None, ""}
            and downstream_provider.get("request_digest") in {None, ""}
            and downstream_provider.get("response_digest") in {None, ""}
            and downstream_provider.get("provider_io_performed") is False
            and downstream_provider.get("cache_consulted") is False
            and _artifact_seals_upstream_empty_receipt(
                artifact_root,
                skip_artifact,
                provider=downstream_provider,
                dependency=dependency,
            )
        )
    except (
        CutoverEvidenceError,
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        return False


def _derive_aox_scientific_branch(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
) -> str | None:
    """Derive the reached AOX branch from sealed scientific artifacts."""

    if _hmmer_upstream_empty_is_proven(payload, artifact_root=artifact_root):
        return "hmmer_upstream_empty"
    try:
        from openzyme_pipeline import aox_similarity

        chain = dict(
            dict(payload.get("scientific_checks") or {}).get("aox_chain") or {}
        )
        artifact_roles = dict(chain.get("artifact_roles") or {})
        artifacts = {
            str(item.get("artifact_id") or ""): dict(item)
            for item in payload.get("artifacts") or []
            if isinstance(item, dict)
        }

        def read_role(role: str) -> bytes:
            artifact = artifacts.get(str(artifact_roles.get(role) or ""))
            if artifact is None:
                raise ValueError(f"missing artifact role: {role}")
            return _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_bytes()

        targets = aox_similarity.parse_candidate_fasta(read_role("target_sequences"))
        candidates = aox_similarity.parse_candidate_fasta(read_role("candidates"))
        if not targets.records:
            return "length_filter_empty"
        if not candidates.records:
            return "motif_filter_empty"
        return "nonempty"
    except (CutoverEvidenceError, OSError, TypeError, ValueError):
        return None


def _artifact_seals_pubmed_safe_evidence(
    artifact_root: Path,
    artifact: Mapping[str, Any],
    *,
    request_digest: str,
    response_digest: str,
    declared_pmids: set[str],
) -> bool:
    try:
        content = _resolve_artifact_path(
            artifact_root,
            str(artifact.get("relative_path") or ""),
        ).read_bytes()
        payload = _strict_json_loads(content.decode("utf-8"))
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError):
        return False

    keyed_values: dict[str, set[str]] = {}

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (str, int)) and not isinstance(item, bool):
                    keyed_values.setdefault(str(key), set()).add(str(item))
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    observed_pmids = keyed_values.get("pmid", set()) | keyed_values.get(
        "external_id", set()
    )
    return (
        "pubmed" in keyed_values.get("provider", set())
        and request_digest in keyed_values.get("request_digest", set())
        and response_digest in keyed_values.get("response_digest", set())
        and bool(declared_pmids)
        and declared_pmids.issubset(observed_pmids)
    )


def _validate_required_live_chain(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
) -> None:
    effective_config = dict(
        dict(dict(payload.get("product_path") or {}).get("launch_receipt") or {}).get(
            "effective_config"
        )
        or {}
    )
    runner_contract_expectations = _runner_contract_expectations_from_config(
        effective_config
    )
    hmmer_upstream_empty = _hmmer_upstream_empty_is_proven(
        payload,
        artifact_root=artifact_root,
    )
    scientific_branch = _derive_aox_scientific_branch(
        payload,
        artifact_root=artifact_root,
    )
    if scientific_branch is None:
        raise CutoverEvidenceError(
            "scientific_branch_unprovable",
            "eligible AOX evidence must derive its reached branch from sealed artifacts",
            details={"identity": "scientific_checks.aox_chain"},
        )
    providers = [dict(item) for item in payload.get("provider_identities") or []]
    provider_names = {str(item.get("provider") or "") for item in providers}
    if not _REQUIRED_PROVIDER_IDS.issubset(provider_names):
        raise CutoverEvidenceError(
            "required_provider_chain_missing",
            "eligible AOX evidence requires PubMed, NCBI, EBI HMMER, and UniProt receipts",
            details={"identity": "provider_identities"},
        )
    provider_by_name = {
        name: [item for item in providers if item.get("provider") == name]
        for name in _REQUIRED_PROVIDER_IDS
    }
    if any(len(records) != 1 for records in provider_by_name.values()):
        raise CutoverEvidenceError(
            "required_provider_receipt_ambiguous",
            "eligible AOX evidence requires exactly one aggregate receipt per required provider",
            details={"identity": "provider_identities"},
        )
    if (
        provider_by_name["pubmed"][0].get("status") != "completed"
        or provider_by_name["ncbi"][0].get("status") != "completed"
    ):
        raise CutoverEvidenceError(
            "required_provider_empty",
            "PubMed and the 13-reference NCBI fetch cannot be empty",
            details={"identity": "provider_identities"},
        )
    for provider in providers:
        canonical_ref_kind = provider.get("canonical_ref_kind")
        digest_invalid = canonical_ref_kind != "upstream_empty" and (
            _DIGEST_PATTERN.fullmatch(str(provider.get("request_digest") or "")) is None
            or _DIGEST_PATTERN.fullmatch(str(provider.get("response_digest") or ""))
            is None
        )
        if (
            not str(provider.get("provider_record_id") or "")
            or canonical_ref_kind
            not in {"engine_invocation", "controlled_operation", "upstream_empty"}
            or (
                canonical_ref_kind == "controlled_operation"
                and (
                    not str(provider.get("operation_id") or "")
                    or not str(provider.get("invocation_id") or "")
                )
            )
            or (
                canonical_ref_kind == "engine_invocation"
                and (
                    provider.get("provider") != "pubmed"
                    or not str(provider.get("invocation_id") or "")
                )
            )
            or (
                canonical_ref_kind == "upstream_empty"
                and (
                    not hmmer_upstream_empty
                    or provider.get("provider") != "uniprot"
                    or provider.get("status") != "upstream_empty"
                    or provider.get("invocation_id") not in {None, ""}
                    or provider.get("operation_id") not in {None, ""}
                    or provider.get("request_digest") not in {None, ""}
                    or provider.get("response_digest") not in {None, ""}
                    or provider.get("provider_io_performed") is not False
                    or provider.get("cache_consulted") is not False
                )
            )
            or provider.get("status") not in {"completed", "empty", "upstream_empty"}
            or provider.get("cache_hit") is not False
            or digest_invalid
        ):
            raise CutoverEvidenceError(
                "provider_receipt_invalid",
                "provider receipts must be terminal, cache-bypassed, and digest-bound",
                details={
                    "identity": f"provider:{provider.get('provider_record_id') or 'unknown'}"
                },
            )
    artifacts = {
        str(item.get("artifact_id") or ""): dict(item)
        for item in payload.get("artifacts") or []
        if isinstance(item, dict)
    }
    pubmed_provider = provider_by_name["pubmed"][0]
    pubmed_source_refs = [
        dict(item)
        for item in pubmed_provider.get("source_refs") or []
        if isinstance(item, dict)
    ]
    declared_pubmed_ids = {str(item.get("pmid") or "") for item in pubmed_source_refs}
    declared_pubmed_source_ids = {
        str(item.get("source_ref_id") or "") for item in pubmed_source_refs
    }
    if (
        not pubmed_source_refs
        or "" in declared_pubmed_ids
        or "" in declared_pubmed_source_ids
        or len(declared_pubmed_ids) != len(pubmed_source_refs)
        or len(declared_pubmed_source_ids) != len(pubmed_source_refs)
        or any(not pmid.isdigit() for pmid in declared_pubmed_ids)
        or declared_pubmed_source_ids
        != {str(item) for item in pubmed_provider.get("source_ref_ids") or []}
    ):
        raise CutoverEvidenceError(
            "pubmed_source_receipt_invalid",
            "required PubMed receipt must bind unique source refs to numeric PMIDs",
            details={"identity": "provider_identities.pubmed"},
        )
    parsed_pubmed_ids: set[str] = set()

    def collect_pubmed_ids(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"pmid", "pubmed_id"} and str(item).isdigit():
                    parsed_pubmed_ids.add(str(item))
                collect_pubmed_ids(item)
        elif isinstance(value, list):
            for item in value:
                collect_pubmed_ids(item)

    for artifact_id in pubmed_provider.get("artifact_ids") or []:
        artifact = artifacts.get(str(artifact_id))
        if artifact is None:
            continue
        try:
            content = _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_text(encoding="utf-8")
            collect_pubmed_ids(_strict_json_loads(content))
        except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError):
            continue
    if not declared_pubmed_ids.issubset(parsed_pubmed_ids):
        raise CutoverEvidenceError(
            "pubmed_artifact_identity_mismatch",
            "sealed PubMed artifacts do not contain every declared PMID",
            details={"identity": "provider_identities.pubmed"},
        )
    engine_invocations = [
        dict(item) for item in payload.get("engine_invocations") or []
    ]
    engine_invocation_map = {
        str(item.get("invocation_id") or ""): item for item in engine_invocations
    }
    if (
        not engine_invocations
        or len(engine_invocation_map) != len(engine_invocations)
        or "" in engine_invocation_map
    ):
        raise CutoverEvidenceError(
            "engine_invocation_chain_invalid",
            "eligible PubMed evidence requires uniquely identified engine invocation receipts",
            details={"identity": "engine_invocations"},
        )
    for invocation_id, invocation in engine_invocation_map.items():
        artifact_refs = [
            dict(item)
            for item in invocation.get("artifact_refs") or []
            if isinstance(item, dict)
        ]
        lane_id = invocation.get("lane_id")
        if (
            invocation.get("engine_name") != "research_tool"
            or invocation.get("status") != "succeeded"
            or not str(invocation.get("task_id") or "")
            or "lane_id" not in invocation
            or (lane_id is not None and (not isinstance(lane_id, str) or not lane_id))
            or not str(invocation.get("input_ref") or "")
            or not str(invocation.get("output_ref") or "")
            or not str(invocation.get("started_at") or "")
            or not str(invocation.get("finished_at") or "")
            or _DIGEST_PATTERN.fullmatch(
                str(invocation.get("input_document_digest") or "")
            )
            is None
            or _DIGEST_PATTERN.fullmatch(
                str(invocation.get("output_document_digest") or "")
            )
            is None
            or not artifact_refs
            or any(
                not str(ref.get("artifact_id") or "")
                or _DIGEST_PATTERN.fullmatch(str(ref.get("content_digest") or ""))
                is None
                for ref in artifact_refs
            )
        ):
            raise CutoverEvidenceError(
                "engine_invocation_receipt_invalid",
                "engine invocation receipts must be terminal and bind documents plus sealed artifacts",
                details={"identity": f"engine_invocation:{invocation_id}"},
            )
    pubmed_invocation = engine_invocation_map.get(
        str(pubmed_provider.get("invocation_id") or "")
    )
    if (
        pubmed_provider.get("canonical_ref_kind") != "engine_invocation"
        or pubmed_provider.get("operation_id") not in {None, ""}
        or pubmed_invocation is None
    ):
        raise CutoverEvidenceError(
            "pubmed_engine_invocation_missing",
            "PubMed receipt must resolve to its real terminal research-tool invocation",
            details={"identity": "provider_identities.pubmed"},
        )
    toolchains = [dict(item) for item in payload.get("toolchain_identities") or []]
    tool_names = {str(item.get("tool") or "") for item in toolchains}
    required_tool_ids = {"mafft", "hmmbuild"}
    if scientific_branch in {"motif_filter_empty", "nonempty"}:
        required_tool_ids.add("hmmalign")
    if scientific_branch == "nonempty":
        required_tool_ids.add("cd-hit")
    if tool_names != required_tool_ids:
        raise CutoverEvidenceError(
            "required_toolchain_missing",
            "eligible AOX evidence requires exactly the toolchains reached by its scientific DAG",
            details={"identity": "toolchain_identities"},
        )
    if any(
        sum(1 for item in toolchains if item.get("tool") == tool_name) != 1
        for tool_name in required_tool_ids
    ):
        raise CutoverEvidenceError(
            "required_toolchain_receipt_ambiguous",
            "eligible AOX evidence requires exactly one aggregate receipt per required tool",
            details={"identity": "toolchain_identities"},
        )
    for toolchain in toolchains:
        if (
            not str(toolchain.get("toolchain_record_id") or "")
            or not str(toolchain.get("toolchain_id") or "")
            or not str(toolchain.get("operation_id") or "")
            or not str(toolchain.get("job_id") or "")
            or toolchain.get("status") != "completed"
            or _DIGEST_PATTERN.fullmatch(str(toolchain.get("image_digest") or ""))
            is None
        ):
            raise CutoverEvidenceError(
                "toolchain_receipt_invalid",
                "toolchain receipts must be completed and bind an operation, job, and image",
                details={
                    "identity": f"toolchain:{toolchain.get('toolchain_record_id') or 'unknown'}"
                },
            )
    operations = [dict(item) for item in payload.get("operations") or []]
    operation_map = {str(item.get("operation_id") or ""): item for item in operations}
    if not operations or len(operation_map) != len(operations) or "" in operation_map:
        raise CutoverEvidenceError(
            "operation_chain_invalid",
            "eligible AOX evidence requires uniquely identified canonical operation receipts",
            details={"identity": "operations"},
        )
    for operation_id, operation in operation_map.items():
        _validate_operation_identity(operation)
        canonical_ref_kind = operation.get("canonical_ref_kind")
        if (
            (
                canonical_ref_kind == "controlled_operation"
                and (
                    not str(operation.get("route_policy_id") or "")
                    or operation.get("selected_backend") not in {"provider_http", "hpc"}
                )
            )
            or (
                canonical_ref_kind == "sandbox_calculation"
                and operation.get("selected_backend") != "sandbox_run"
            )
            or not str(operation.get("backend_run_id") or "")
            or _DIGEST_PATTERN.fullmatch(
                str(operation.get("source_snapshot_digest") or "")
            )
            is None
        ):
            raise CutoverEvidenceError(
                "operation_runtime_receipt_invalid",
                "operation receipts must bind their canonical backend run and source snapshot identities",
                details={"identity": f"operation:{operation_id}"},
            )
    receipt_operation_ids = {
        str(item.get("operation_id") or "")
        for item in providers
        if item.get("canonical_ref_kind") == "controlled_operation"
    }
    receipt_operation_ids.update(
        str(item.get("operation_id") or "") for item in toolchains
    )
    if not receipt_operation_ids.issubset(operation_map):
        raise CutoverEvidenceError(
            "receipt_operation_missing",
            "every provider and toolchain receipt must resolve to a controlled operation",
            details={"identity": "operations"},
        )
    for provider in providers:
        artifact_ids = {
            str(item) for item in provider.get("artifact_ids") or [] if str(item)
        }
        if provider.get("canonical_ref_kind") == "controlled_operation":
            operation = operation_map[str(provider["operation_id"])]
            output_refs = {
                str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
                for ref in operation.get("outputs") or []
                if isinstance(ref, dict)
            }
            if (
                operation.get("canonical_ref_kind") != "controlled_operation"
                or operation.get("selected_backend") != "provider_http"
                or operation.get("backend_run_id") != provider.get("invocation_id")
                or not str(operation.get("route_policy_id") or "").endswith(
                    ".provider:v1"
                )
            ):
                raise CutoverEvidenceError(
                    "provider_operation_receipt_mismatch",
                    "provider receipts must bind the controlled route and exact invocation",
                    details={
                        "identity": f"provider:{provider.get('provider_record_id') or 'unknown'}"
                    },
                )
            lineage_invalid = (
                not artifact_ids
                or not artifact_ids.issubset(artifacts)
                or any(
                    artifacts[artifact_id].get("scope") != "formal"
                    or artifacts[artifact_id].get("origin") != "operation"
                    or output_refs.get(artifact_id)
                    != artifacts[artifact_id].get("content_digest")
                    for artifact_id in artifact_ids
                )
                or not any(
                    _artifact_seals_provider_response(
                        artifact_root,
                        artifacts[artifact_id],
                        response_digest=str(provider.get("response_digest") or ""),
                    )
                    for artifact_id in artifact_ids
                )
            )
        elif provider.get("canonical_ref_kind") == "engine_invocation":
            invocation = engine_invocation_map[str(provider["invocation_id"])]
            invocation_artifact_refs = {
                str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
                for ref in invocation.get("artifact_refs") or []
                if isinstance(ref, dict)
            }
            lineage_invalid = (
                provider.get("provider") != "pubmed"
                or not artifact_ids
                or not artifact_ids.issubset(artifacts)
                or any(
                    artifacts[artifact_id].get("scope") != "formal"
                    or artifacts[artifact_id].get("origin") != "engine_invocation"
                    or dict(artifacts[artifact_id].get("provenance") or {}).get(
                        "invocation_id"
                    )
                    != invocation.get("invocation_id")
                    or invocation_artifact_refs.get(artifact_id)
                    != artifacts[artifact_id].get("content_digest")
                    for artifact_id in artifact_ids
                )
                or not any(
                    _artifact_seals_pubmed_safe_evidence(
                        artifact_root,
                        artifacts[artifact_id],
                        request_digest=str(provider.get("request_digest") or ""),
                        response_digest=str(provider.get("response_digest") or ""),
                        declared_pmids=declared_pubmed_ids,
                    )
                    for artifact_id in artifact_ids
                )
            )
        else:
            provider_dependencies = dict(
                dict(payload.get("scientific_checks") or {}).get("aox_chain") or {}
            ).get("provider_dependencies")
            dependency = (
                dict(provider_dependencies[0])
                if isinstance(provider_dependencies, list)
                and len(provider_dependencies) == 1
                and isinstance(provider_dependencies[0], dict)
                else {}
            )
            skip_artifact_id = str(dependency.get("skip_artifact_id") or "")
            skip_artifact = artifacts.get(skip_artifact_id)
            lineage_invalid = (
                not hmmer_upstream_empty
                or provider.get("provider") != "uniprot"
                or artifact_ids != {skip_artifact_id}
                or skip_artifact is None
                or not _artifact_seals_upstream_empty_receipt(
                    artifact_root,
                    skip_artifact or {},
                    provider=provider,
                    dependency=dependency,
                )
            )
        if lineage_invalid:
            raise CutoverEvidenceError(
                "provider_artifact_lineage_invalid",
                "provider receipts must resolve to their canonical owner and sealed evidence",
                details={
                    "identity": f"provider:{provider.get('provider_record_id') or 'unknown'}"
                },
            )
    for toolchain in toolchains:
        operation = operation_map[str(toolchain["operation_id"])]
        _validate_attested_toolchain_receipt(
            toolchain,
            operation=operation,
            prerequisites=dict(
                dict(payload.get("clean_world") or {}).get("allowed_prerequisites")
                or {}
            ),
            runner_contract_expectations=runner_contract_expectations,
            error_code="toolchain_operation_receipt_mismatch",
        )
        if (
            operation.get("selected_backend") != "hpc"
            or operation.get("backend_run_id") != toolchain.get("job_id")
            or not str(operation.get("route_policy_id") or "").endswith(".hpc:v1")
        ):
            raise CutoverEvidenceError(
                "toolchain_operation_receipt_mismatch",
                "HPC tool receipts must bind the controlled route and exact backend job",
                details={
                    "identity": f"toolchain:{toolchain.get('toolchain_record_id') or 'unknown'}"
                },
            )
    tasks = [dict(item) for item in payload.get("tasks") or []]
    role_to_ids: dict[str, list[str]] = {}
    for task in tasks:
        role_to_ids.setdefault(str(task.get("role") or ""), []).append(
            str(task.get("task_id") or "")
        )
    if any(len(role_to_ids.get(role, [])) != 1 for role in _REQUIRED_TASK_ROLES):
        raise CutoverEvidenceError(
            "required_task_chain_missing",
            "eligible AOX evidence requires one durable researcher, executor, and reporter task",
            details={"identity": "tasks"},
        )
    researcher_task = next(task for task in tasks if task.get("role") == "researcher")
    scientific_chain = dict(
        dict(payload.get("scientific_checks") or {}).get("aox_chain") or {}
    )
    artifact_roles = dict(scientific_chain.get("artifact_roles") or {})
    primary_artifact_id = str(artifact_roles.get("literature_evidence") or "")
    provider_artifact_ids = {
        str(item) for item in pubmed_provider.get("artifact_ids") or [] if str(item)
    }
    invocation_artifact_ids = {
        str(item.get("artifact_id") or "")
        for item in pubmed_invocation.get("artifact_refs") or []
        if isinstance(item, dict) and str(item.get("artifact_id") or "")
    }
    if (
        scientific_chain.get("literature_provider_record_id")
        != pubmed_provider.get("provider_record_id")
        or not primary_artifact_id
        or provider_artifact_ids != {primary_artifact_id}
        or invocation_artifact_ids != {primary_artifact_id}
    ):
        raise CutoverEvidenceError(
            "pubmed_primary_lineage_invalid",
            "the selected PubMed artifact must close exactly through its aggregate provider and invocation receipts",
            details={"identity": "scientific_checks.aox_chain.literature_evidence"},
        )
    researcher_evidence_refs = researcher_task.get("evidence_refs")
    primary_evidence_ref = f"artifact:{primary_artifact_id}"
    if (
        not isinstance(researcher_evidence_refs, list)
        or any(not isinstance(item, str) for item in researcher_evidence_refs)
        or primary_evidence_ref not in researcher_evidence_refs
    ):
        raise CutoverEvidenceError(
            "pubmed_primary_task_binding_invalid",
            "the researcher task.finish receipt must select the primary PubMed artifact",
            details={
                "identity": f"task:{researcher_task.get('task_id')}:evidence_refs"
            },
        )
    if pubmed_invocation.get("task_id") != researcher_task.get("task_id"):
        raise CutoverEvidenceError(
            "pubmed_invocation_task_mismatch",
            "the selected PubMed invocation must belong to the researcher task",
            details={"identity": "provider_identities.pubmed.invocation_id"},
        )
    researcher_lane_id = researcher_task.get("lane_id")
    if (
        "lane_id" not in researcher_task
        or (
            researcher_lane_id is not None
            and (not isinstance(researcher_lane_id, str) or not researcher_lane_id)
        )
        or pubmed_invocation.get("lane_id") != researcher_lane_id
    ):
        raise CutoverEvidenceError(
            "pubmed_invocation_lane_mismatch",
            "the selected PubMed invocation lane must exactly match the researcher task lane, including an absent lane",
            details={"identity": "provider_identities.pubmed.invocation_id"},
        )
    primary_artifact = artifacts.get(primary_artifact_id)
    primary_provenance = (
        {}
        if primary_artifact is None
        else dict(primary_artifact.get("provenance") or {})
    )
    if (
        primary_artifact is None
        or primary_provenance.get("provider") != "pubmed"
        or primary_provenance.get("invocation_id")
        != pubmed_invocation.get("invocation_id")
        or primary_provenance.get("task_id") != researcher_task.get("task_id")
        or "lane_id" not in primary_provenance
        or primary_provenance.get("lane_id") != researcher_lane_id
    ):
        raise CutoverEvidenceError(
            "pubmed_primary_artifact_scope_mismatch",
            "the selected PubMed artifact must preserve exact researcher invocation scope",
            details={"identity": f"artifact:{primary_artifact_id}"},
        )
    if any(
        not {
            "source_ref_id",
            "pmid",
            "task_id",
            "lane_id",
            "invocation_id",
            "evidence_artifact_id",
        }.issubset(source_ref)
        or source_ref.get("task_id") != researcher_task.get("task_id")
        or source_ref.get("lane_id") != researcher_lane_id
        or source_ref.get("invocation_id") != pubmed_invocation.get("invocation_id")
        or source_ref.get("evidence_artifact_id") != primary_artifact_id
        for source_ref in pubmed_source_refs
    ):
        raise CutoverEvidenceError(
            "pubmed_primary_source_scope_mismatch",
            "every selected PubMed source must preserve exact task, lane, invocation, and artifact lineage",
            details={"identity": "provider_identities.pubmed.source_refs"},
        )
    product_path = dict(payload.get("product_path") or {})
    campaign_identity = dict(payload.get("identity") or {})
    expected_task_ids = {
        role: role_to_ids[role][0] for role in sorted(_REQUIRED_TASK_ROLES)
    }
    launch_receipt = dict(product_path.get("launch_receipt") or {})
    sandbox_runtime_identity = dict(
        launch_receipt.get("sandbox_runtime_identity") or {}
    )
    clean_world = dict(payload.get("clean_world") or {})
    required_digests = (
        "entry_message_digest",
        "workspace_projection_digest",
        "event_log_digest",
        "runtime_config_digest",
    )
    if (
        product_path.get("entry_message_count") != 1
        or product_path.get("canonical_api_only") is not True
        or product_path.get("cache_hit") is not False
        or not str(product_path.get("session_id") or "")
        or not str(product_path.get("entry_message_id") or "")
        or not str(product_path.get("final_master_response_id") or "")
        or product_path.get("task_ids_by_role") != expected_task_ids
        or any(
            _DIGEST_PATTERN.fullmatch(str(product_path.get(key) or "")) is None
            for key in required_digests
        )
        or launch_receipt.get("root_identity") != clean_world.get("root_identity")
        or launch_receipt.get("hpc_workspace_label")
        != clean_world.get("hpc_workspace_label")
        or launch_receipt.get("sqlite_initialized_fresh") is not True
        or launch_receipt.get("artifact_root_bound") is not True
        or launch_receipt.get("blob_root_bound") is not True
        or launch_receipt.get("sandbox_root_bound") is not True
    ):
        raise CutoverEvidenceError(
            "canonical_product_path_incomplete",
            "eligible AOX evidence requires root-bound Host launch and public API receipts",
            details={"identity": "product_path"},
        )
    if (
        sandbox_runtime_identity.get("image_digest")
        != campaign_identity.get("image_digest")
        or sandbox_runtime_identity.get("pipeline_sdk_digest")
        != campaign_identity.get("sdk_digest")
        or _DIGEST_PATTERN.fullmatch(
            str(sandbox_runtime_identity.get("runtime_identity_digest") or "")
        )
        is None
        or not str(sandbox_runtime_identity.get("sandbox_protocol_version") or "")
    ):
        raise CutoverEvidenceError(
            "sandbox_runtime_identity_drift",
            "sealed Host sandbox preflight identity differs from the campaign identity",
            details={
                "identity": "product_path.launch_receipt.sandbox_runtime_identity"
            },
        )
    approvals = [dict(item) for item in payload.get("approvals") or []]
    if not approvals or any(
        approval.get("decision") != "approved"
        or str(approval.get("operation_id") or "") not in operation_map
        or operation_map[str(approval.get("operation_id") or "")].get(
            "canonical_ref_kind"
        )
        != "controlled_operation"
        for approval in approvals
    ):
        raise CutoverEvidenceError(
            "approval_chain_invalid",
            "eligible AOX evidence requires an approved controlled-operation receipt",
            details={"identity": "approvals"},
        )
    approval_mode = str(launch_receipt.get("approval_mode") or "")
    campaign_attempt_number = launch_receipt.get("campaign_attempt_number")
    public_api_receipt_digest = str(
        launch_receipt.get("public_api_receipt_digest") or ""
    )
    browser_approval = launch_receipt.get("browser_approval_receipt")
    browser_observation = launch_receipt.get("browser_observation_receipt")
    if (
        approval_mode not in {"public-explicit", "chrome-once"}
        or not isinstance(campaign_attempt_number, int)
        or isinstance(campaign_attempt_number, bool)
        or campaign_attempt_number <= 0
        or _DIGEST_PATTERN.fullmatch(public_api_receipt_digest) is None
    ):
        raise CutoverEvidenceError(
            "campaign_launch_attestation_invalid",
            "eligible AOX evidence lacks the exact public conductor launch attestation",
            details={"identity": "product_path.launch_receipt"},
        )
    public_api_receipts = _validate_public_api_receipts(
        product_path,
        expected_digest=public_api_receipt_digest,
        payload=payload,
    )
    _validate_public_final_snapshot_artifacts(
        payload,
        artifact_root=artifact_root,
        public_api_receipts=public_api_receipts,
    )
    browser_required = approval_mode == "chrome-once" and campaign_attempt_number == 1
    if browser_required and not isinstance(browser_approval, dict):
        raise CutoverEvidenceError(
            "browser_approval_receipt_missing",
            "chrome-once positive 1 requires a sealed same-operation approval receipt",
            details={
                "identity": "product_path.launch_receipt.browser_approval_receipt"
            },
        )
    if not browser_required and (
        browser_approval is not None or browser_observation is not None
    ):
        raise CutoverEvidenceError(
            "browser_approval_receipt_unexpected",
            "browser approval receipt is only valid for chrome-once positive 1",
            details={
                "identity": "product_path.launch_receipt.browser_approval_receipt"
            },
        )
    if isinstance(browser_approval, dict):
        browser_report = dict(payload.get("report") or {})
        approval_id = str(browser_approval.get("approval_id") or "")
        resolve_route = f"/v3/approvals/{approval_id}/resolve"
        if any(
            receipt.get("method") == "POST" and receipt.get("route") == resolve_route
            for receipt in public_api_receipts
        ):
            raise CutoverEvidenceError(
                "browser_approval_driver_shortcut_detected",
                "campaign driver called the Chrome-reserved approval route",
                details={"identity": "product_path.public_api_receipts"},
            )
        operation_id = str(browser_approval.get("operation_id") or "")
        operation = operation_map.get(operation_id)
        operation_identity = (
            {}
            if operation is None
            else dict(operation.get("operation_identity_material") or {})
        )
        approval = next(
            (
                item
                for item in approvals
                if str(item.get("approval_id") or "") == approval_id
            ),
            None,
        )
        pre_cursor = browser_approval.get("pre_event_cursor")
        resolution_cursor = browser_approval.get("resolution_event_cursor")
        continuation_cursor = browser_approval.get("continuation_event_cursor")
        resolution_record = browser_approval.get("resolution_event_record")
        continuation_record = browser_approval.get("continuation_event_record")
        cursor_values = (pre_cursor, resolution_cursor, continuation_cursor)
        continuation_id = str(browser_approval.get("continuation_id") or "")
        effective_config = dict(launch_receipt.get("effective_config") or {})
        driver_config = dict(effective_config.get("driver") or {})
        event_read_bound = (
            any(
                receipt.get("method") == "GET"
                and _event_replay_route_semantics(str(receipt.get("route") or ""))
                == (
                    f"/v3/sessions/{product_path.get('session_id')}/events",
                    int(pre_cursor),
                )
                for receipt in public_api_receipts
            )
            if isinstance(pre_cursor, int) and not isinstance(pre_cursor, bool)
            else False
        )
        if (
            set(browser_approval) != _BROWSER_APPROVAL_RECEIPT_KEYS
            or browser_approval.get("schema_id") != "aox_browser_approval_receipt@2"
            or browser_approval.get("approval_mode") != "chrome-once"
            or browser_approval.get("ui_channel") != "same_process_loopback_web_ui"
            or browser_approval.get("session_id") != product_path.get("session_id")
            or browser_approval.get("driver_resolve_route_absent") is not True
            or not isinstance(browser_approval.get("host_process_id"), int)
            or int(browser_approval.get("host_process_id") or 0) <= 0
            or any(
                not isinstance(cursor, int) or isinstance(cursor, bool)
                for cursor in cursor_values
            )
            or not (int(pre_cursor) < int(resolution_cursor) < int(continuation_cursor))
            or not str(browser_approval.get("resolution_event_id") or "")
            or not str(browser_approval.get("continuation_event_id") or "")
            or not str(browser_approval.get("resolution_actor_ref") or "")
            or not str(browser_approval.get("continuation_id") or "")
            or _DIGEST_PATTERN.fullmatch(
                str(browser_approval.get("served_ui_dist_digest") or "")
            )
            is None
            or browser_approval.get("served_ui_dist_digest")
            != driver_config.get("ui_dist_digest")
            or _DIGEST_PATTERN.fullmatch(
                str(browser_approval.get("observation_challenge") or "")
            )
            is None
            or browser_approval.get("page_url")
            != "loopback://same-process/ui/?project_id=aox-blank-world-cutover"
            or _DIGEST_PATTERN.fullmatch(
                str(browser_approval.get("pre_workspace_digest") or "")
            )
            is None
            or _DIGEST_PATTERN.fullmatch(
                str(browser_approval.get("post_workspace_digest") or "")
            )
            is None
            or operation is None
            or operation.get("canonical_ref_kind") != "controlled_operation"
            or operation.get("status") != "completed"
            or browser_approval.get("operation_digest")
            != operation.get("operation_identity_digest")
            or browser_approval.get("sandbox_run_id") != operation.get("sandbox_run_id")
            or browser_approval.get("sandbox_workspace_id")
            != operation_identity.get("sandbox_workspace_id")
            or approval is None
            or approval.get("decision") != "approved"
            or approval.get("operation_id") != operation_id
            or approval.get("operation_identity_digest")
            != browser_approval.get("operation_digest")
            or not _browser_workspace_snapshots_are_valid(
                browser_approval,
                public_api_receipts=public_api_receipts,
            )
            or not _browser_durable_event_is_valid(
                resolution_record,
                event_type="approval.resolved",
                session_id=str(product_path.get("session_id") or ""),
                approval_id=approval_id,
                operation_id=operation_id,
                operation_digest=str(browser_approval.get("operation_digest") or ""),
                continuation_id=continuation_id,
            )
            or not _browser_durable_event_is_valid(
                continuation_record,
                event_type="sdk_controlled_operation.approval_resolved",
                session_id=str(product_path.get("session_id") or ""),
                approval_id=approval_id,
                operation_id=operation_id,
                operation_digest=str(browser_approval.get("operation_digest") or ""),
                continuation_id=continuation_id,
            )
            or dict(resolution_record or {}).get("event_id")
            != browser_approval.get("resolution_event_id")
            or dict(resolution_record or {}).get("cursor") != resolution_cursor
            or dict(resolution_record or {}).get("actor_ref")
            != browser_approval.get("resolution_actor_ref")
            or dict(resolution_record or {}).get("command_id")
            != browser_approval.get("resolution_command_id")
            or dict(continuation_record or {}).get("event_id")
            != browser_approval.get("continuation_event_id")
            or dict(continuation_record or {}).get("cursor") != continuation_cursor
            or not event_read_bound
            or not _browser_event_response_bindings_are_valid(
                browser_approval,
                public_api_receipts=public_api_receipts,
            )
            or not _browser_observation_receipt_is_valid(
                browser_observation,
                browser=browser_approval,
                effective_config=effective_config,
                product_path=product_path,
                operation={} if operation is None else operation,
                report=browser_report,
                public_api_receipts=public_api_receipts,
            )
        ):
            raise CutoverEvidenceError(
                "browser_approval_receipt_invalid",
                "Chrome receipt does not close over one approved terminal operation identity",
                details={
                    "identity": "product_path.launch_receipt.browser_approval_receipt"
                },
            )
    report = dict(payload.get("report") or {})
    source_ref_ids = {
        str(source_ref_id)
        for provider in providers
        for source_ref_id in provider.get("source_ref_ids") or []
        if str(source_ref_id)
    }
    report_source_ids = {str(item) for item in report.get("source_ref_ids") or []}
    claim_links = [
        dict(item)
        for item in report.get("claim_source_links") or []
        if isinstance(item, dict)
    ]
    if (
        not _report_publish_receipt_is_valid(report)
        or report.get("session_id") != product_path.get("session_id")
        or report.get("task_id") != expected_task_ids.get("reporter")
        or not report_source_ids
        or not report_source_ids.issubset(source_ref_ids)
        or not report_source_ids.intersection(declared_pubmed_source_ids)
        or not claim_links
        or any(
            not set(str(item) for item in link.get("source_ref_ids") or []).issubset(
                report_source_ids
            )
            for link in claim_links
        )
    ):
        raise CutoverEvidenceError(
            "report_source_lineage_invalid",
            "published report claims must resolve to sealed provider source identities",
            details={"identity": "report.claim_source_links"},
        )
    scientific_checks = dict(payload.get("scientific_checks") or {})
    scoring = dict(scientific_checks.get("scoring") or {})
    identity = dict(payload.get("identity") or {})
    if scoring.get("scoring_contract_digest") != identity.get(
        "scoring_contract_digest"
    ) or scoring.get("scoring_implementation_digest") != identity.get(
        "scoring_implementation_digest"
    ):
        raise CutoverEvidenceError(
            "scoring_identity_drift",
            "campaign scoring identity differs from the recomputed scoring check",
            details={"identity": "scientific_checks.scoring"},
        )


def _validate_attested_toolchain_receipt(
    toolchain: Mapping[str, Any],
    *,
    operation: Mapping[str, Any],
    prerequisites: Mapping[str, object],
    runner_contract_expectations: Mapping[str, Mapping[str, str]],
    error_code: str,
) -> None:
    tool_name = str(toolchain.get("tool") or "")
    expected = AOX_TOOLCHAIN_RUNTIME_CONTRACTS.get(tool_name)
    toolchain_digests = dict(prerequisites.get("toolchain_image_digests") or {})
    operation_identity = dict(operation.get("operation_identity_material") or {})
    expected_runner_contract = runner_contract_expectations.get(
        "" if expected is None else expected["tool_id"]
    )
    if (
        expected is None
        or toolchain.get("toolchain_id") != expected["toolchain_id"]
        or operation_identity.get("toolchain_id") != expected["toolchain_id"]
        or toolchain.get("runtime_identity_schema")
        != "mcp_hpc_toolchain_runtime_identity@1"
        or toolchain.get("attestation_scope") != "same_ssh_login_shell_pre_exec"
        or toolchain.get("execution_mode") != "ssh"
        or toolchain.get("tool_id") != expected["tool_id"]
        or toolchain.get("adapter_id") != expected["adapter_id"]
        or toolchain.get("command_template_id") != expected["command_template_id"]
        or expected_runner_contract is None
        or toolchain.get("runner_contract_digest")
        != expected_runner_contract.get("runner_contract_digest")
        or toolchain.get("adapter_id") != expected_runner_contract.get("adapter_id")
        or toolchain.get("command_template_id")
        != expected_runner_contract.get("command_template_id")
        or toolchain.get("image_digest")
        != toolchain_digests.get(expected["toolchain_id"])
    ):
        raise CutoverEvidenceError(
            error_code,
            "toolchain receipt must bind the runner-attested same-shell SIF identity and sealed prerequisite",
            details={
                "identity": f"toolchain:{toolchain.get('toolchain_record_id') or 'unknown'}"
            },
        )


def _event_replay_route_semantics(
    route: str,
) -> tuple[str, int] | None:
    match = re.fullmatch(
        r"(?P<path>/v3/sessions/(?P<session>[A-Za-z0-9._-]+)/events)"
        r"\?replay=1&after_cursor=(?P<cursor>0|[1-9][0-9]*)",
        route,
    )
    if match is None or _ATTEMPT_ID_PATTERN.fullmatch(match.group("session")) is None:
        return None
    return match.group("path"), int(match.group("cursor"))


def _public_api_route_is_canonical(
    method: str,
    route: str,
    *,
    allow_legacy_scientific_mutations: bool = False,
) -> bool:
    event_semantics = _event_replay_route_semantics(route)
    if event_semantics is not None:
        return method == "GET"
    if "?" in route:
        return False
    segments = [segment for segment in route.split("/") if segment]
    if method == "GET" and route == "/v3/runtime/health":
        return True
    if method == "POST" and route == "/v3/sessions":
        return True
    if len(segments) == 4 and segments[:2] == ["v3", "sessions"]:
        if _ATTEMPT_ID_PATTERN.fullmatch(segments[2]) is None:
            return False
        return (
            method == "GET"
            and segments[3]
            in {
                "workspace",
                "events",
                "pending-approvals",
                "scientific-attempts",
            }
        ) or (
            method == "POST"
            and segments[3]
            in (
                {
                    "messages",
                    "scientific-attempt-authorizations",
                    "scientific-attempt-commands",
                }
                if allow_legacy_scientific_mutations
                else {"messages", "scientific-attempt-authorizations"}
            )
        )
    if len(segments) == 5 and segments[:2] == ["v3", "sessions"]:
        return bool(
            _ATTEMPT_ID_PATTERN.fullmatch(segments[2]) is not None
            and (
                (method == "POST" and segments[3:] == ["runtime", "drain"])
                or (
                    allow_legacy_scientific_mutations
                    and method == "POST"
                    and segments[3]
                    in {
                        "scientific-attempt-admissions",
                        "scientific-attempt-closures",
                    }
                    and segments[4] == "finalize"
                )
            )
        )
    if len(segments) == 6 and segments[:2] == ["v3", "sessions"]:
        return (
            _ATTEMPT_ID_PATTERN.fullmatch(segments[2]) is not None
            and method == "GET"
            and segments[3:5] == ["runtime", "commands"]
            and bool(segments[5])
        )
    if len(segments) == 4 and segments[:2] == ["v3", "approvals"]:
        return (
            _ATTEMPT_ID_PATTERN.fullmatch(segments[2]) is not None
            and method == "POST"
            and segments[3] == "resolve"
        )
    if len(segments) == 8 and segments[:2] == ["v3", "sessions"]:
        return bool(
            method == "GET"
            and _ATTEMPT_ID_PATTERN.fullmatch(segments[2]) is not None
            and segments[3] == "scientific-attempts"
            and segments[4]
            and segments[5] == "selections"
            and segments[6]
            and segments[7] == "evidence"
        )
    return False


def _public_response_binding_is_valid(
    value: object,
    *,
    receipts: Sequence[Mapping[str, Any]],
    expected_semantic_digest: str,
    expected_route: str | None = None,
) -> bool:
    if not isinstance(value, dict):
        return False
    binding = dict(value)
    sequence = binding.get("receipt_sequence")
    if (
        set(binding) != _PUBLIC_RESPONSE_BINDING_KEYS
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence <= 0
        or binding.get("response_semantic_digest") != expected_semantic_digest
        or (expected_route is not None and binding.get("route") != expected_route)
    ):
        return False
    receipt = next(
        (item for item in receipts if item.get("sequence") == sequence),
        None,
    )
    return bool(
        receipt is not None
        and receipt.get("method") == "GET"
        and binding.get("route") == receipt.get("route")
        and binding.get("response_digest") == receipt.get("response_digest")
        and binding.get("response_semantic_digest")
        == receipt.get("response_semantic_digest")
    )


def _validate_public_api_receipts(
    product_path: Mapping[str, Any],
    *,
    expected_digest: str,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_receipts = product_path.get("public_api_receipts")
    receipts = (
        [dict(item) for item in raw_receipts if isinstance(item, dict)]
        if isinstance(raw_receipts, list)
        else []
    )
    session_id = str(product_path.get("session_id") or "")
    entry_route = f"/v3/sessions/{session_id}/messages"
    workspace_route = f"/v3/sessions/{session_id}/workspace"
    drain_route = f"/v3/sessions/{session_id}/runtime/drain"
    config = dict(
        dict(product_path.get("launch_receipt") or {}).get("effective_config") or {}
    )
    driver = dict(config.get("driver") or {})
    workflow_ref = str(dict(payload.get("identity") or {}).get("workflow_ref") or "")
    entry_message_digest = str(product_path.get("entry_message_digest") or "")
    expected_message_request_digest = canonical_digest(
        {
            "message_digest": entry_message_digest,
            "skill_keys": [workflow_ref],
        }
    )
    expected_formal_create_digest = canonical_digest(
        {
            "session_id": session_id,
            "project_id": "aox-blank-world-cutover",
            "objective": (
                "Run the canonical blank-world AOX/HMM product path and publish "
                "a source-linked scientific report."
            ),
            "title": "AOX blank-world formal",
        }
    )
    expected_drain_digest = canonical_digest(
        {
            "max_signals": driver.get("max_signals_per_drain"),
            "max_steps_per_agent": driver.get("max_steps_per_agent"),
            "auto_enqueue_ready_tasks": False,
        }
    )
    valid = (
        bool(receipts)
        and len(receipts) == len(raw_receipts or [])
        and canonical_digest(receipts) == expected_digest
        and [item.get("sequence") for item in receipts]
        == list(range(1, len(receipts) + 1))
        and sum(
            item.get("method") == "POST" and item.get("route") == entry_route
            for item in receipts
        )
        == 1
    )
    for receipt in receipts:
        sequence = receipt.get("sequence")
        status_code = receipt.get("status_code")
        method = str(receipt.get("method") or "")
        route = str(receipt.get("route") or "")
        valid = valid and (
            set(receipt) == _PUBLIC_API_RECEIPT_KEYS
            and isinstance(sequence, int)
            and not isinstance(sequence, bool)
            and isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 200 <= status_code < 300
            and _public_api_route_is_canonical(
                method,
                route,
                allow_legacy_scientific_mutations=(
                    payload.get("schema_id") == ATTEMPT_BUNDLE_SCHEMA_ID_V2
                ),
            )
            and _DIGEST_PATTERN.fullmatch(str(receipt.get("request_digest") or ""))
            is not None
            and _DIGEST_PATTERN.fullmatch(str(receipt.get("response_digest") or ""))
            is not None
            and _DIGEST_PATTERN.fullmatch(
                str(receipt.get("response_semantic_digest") or "")
            )
            is not None
        )
        event_semantics = _event_replay_route_semantics(route)
        if event_semantics is not None:
            valid = valid and receipt.get("request_digest") == canonical_digest(
                {"replay": True, "after_cursor": event_semantics[1]}
            )
        elif method == "GET":
            valid = valid and receipt.get("request_digest") == canonical_digest({})
        elif method == "POST" and route.endswith("/runtime/drain"):
            valid = valid and (
                status_code == 202
                and receipt.get("request_digest") == expected_drain_digest
            )
        elif method == "POST" and route.startswith("/v3/approvals/"):
            valid = valid and receipt.get("request_digest") == canonical_digest(
                {"decision": "approved"}
            )
    matching_creates = [
        item
        for item in receipts
        if item.get("method") == "POST"
        and item.get("route") == "/v3/sessions"
        and item.get("request_digest") == expected_formal_create_digest
    ]
    matching_messages = [
        item
        for item in receipts
        if item.get("method") == "POST" and item.get("route") == entry_route
    ]
    matching_drains = [
        item
        for item in receipts
        if item.get("method") == "POST" and item.get("route") == drain_route
    ]
    runtime_command_route_prefix = f"/v3/sessions/{session_id}/runtime/commands/"
    matching_runtime_commands = [
        item
        for item in receipts
        if item.get("method") == "GET"
        and str(item.get("route") or "").startswith(runtime_command_route_prefix)
    ]
    runtime_command_routes = {
        str(item.get("route") or "") for item in matching_runtime_commands
    }
    valid = valid and all(
        item.get("status_code") == 200 for item in matching_runtime_commands
    )
    matching_workspaces = [
        item
        for item in receipts
        if item.get("method") == "GET" and item.get("route") == workspace_route
    ]
    matching_events = [
        item
        for item in receipts
        if item.get("method") == "GET"
        and (_event_replay_route_semantics(str(item.get("route") or "")) or (None,))[0]
        == f"/v3/sessions/{session_id}/events"
    ]
    if (
        len(matching_creates) != 1
        or len(matching_messages) != 1
        or not matching_drains
        or len(runtime_command_routes) != len(matching_drains)
        or not matching_workspaces
        or not matching_events
        or matching_messages[0].get("request_digest") != expected_message_request_digest
    ):
        valid = False
    else:
        create_sequence = int(matching_creates[0]["sequence"])
        message_sequence = int(matching_messages[0]["sequence"])
        ordered_drain_sequences = sorted(
            int(item["sequence"]) for item in matching_drains
        )
        first_drain_sequence = ordered_drain_sequences[0]
        valid = valid and (
            create_sequence < message_sequence < first_drain_sequence
            and any(
                int(item["sequence"]) > first_drain_sequence
                for item in matching_workspaces
            )
            and any(
                int(item["sequence"]) > first_drain_sequence for item in matching_events
            )
            and all(
                any(
                    int(command["sequence"]) > drain_sequence
                    and (
                        drain_index + 1 == len(ordered_drain_sequences)
                        or int(command["sequence"])
                        < ordered_drain_sequences[drain_index + 1]
                    )
                    for command in matching_runtime_commands
                )
                for drain_index, drain_sequence in enumerate(ordered_drain_sequences)
            )
        )
    final_workspace_digest = str(
        product_path.get("public_final_workspace_digest") or ""
    )
    final_event_digest = str(product_path.get("public_final_event_stream_digest") or "")
    valid = valid and (
        _DIGEST_PATTERN.fullmatch(final_workspace_digest) is not None
        and _DIGEST_PATTERN.fullmatch(final_event_digest) is not None
        and _public_response_binding_is_valid(
            product_path.get("public_final_workspace_response_binding"),
            receipts=receipts,
            expected_semantic_digest=final_workspace_digest,
            expected_route=workspace_route,
        )
        and _public_response_binding_is_valid(
            product_path.get("public_final_event_response_binding"),
            receipts=receipts,
            expected_semantic_digest=final_event_digest,
        )
        and (
            _event_replay_route_semantics(
                str(
                    dict(
                        product_path.get("public_final_event_response_binding") or {}
                    ).get("route")
                    or ""
                )
            )
            or (None,)
        )[0]
        == f"/v3/sessions/{session_id}/events"
    )
    if not valid:
        raise CutoverEvidenceError(
            "public_api_receipt_attestation_invalid",
            "eligible AOX evidence requires an ordered closed public API receipt chain",
            details={"identity": "product_path.public_api_receipts"},
        )
    return receipts


def _validate_public_final_snapshot_artifacts(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    public_api_receipts: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    product_path = dict(payload.get("product_path") or {})
    artifact_map = {
        str(item.get("artifact_id") or ""): dict(item)
        for item in payload.get("artifacts") or []
        if isinstance(item, dict)
    }
    workspace_artifact_id = str(
        product_path.get("public_final_workspace_artifact_id") or ""
    )
    event_artifact_id = str(
        product_path.get("public_final_event_replay_artifact_id") or ""
    )
    workspace_artifact = artifact_map.get(workspace_artifact_id)
    event_artifact = artifact_map.get(event_artifact_id)
    try:
        if workspace_artifact is None or event_artifact is None:
            raise ValueError("missing public final snapshot artifact")
        workspace_bytes = _resolve_artifact_path(
            artifact_root,
            str(workspace_artifact.get("relative_path") or ""),
        ).read_bytes()
        event_bytes = _resolve_artifact_path(
            artifact_root,
            str(event_artifact.get("relative_path") or ""),
        ).read_bytes()
        workspace_envelope = _strict_json_loads(workspace_bytes.decode("utf-8"))
        event_envelope = _strict_json_loads(event_bytes.decode("utf-8"))
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "public_final_snapshot_artifact_invalid",
            "final public workspace/event preimage artifacts are missing or unreadable",
            details={"identity": "product_path.public_final_snapshot_artifacts"},
        ) from exc
    if not isinstance(workspace_envelope, dict) or not isinstance(event_envelope, dict):
        raise CutoverEvidenceError(
            "public_final_snapshot_artifact_invalid",
            "final public snapshot artifacts must be JSON objects",
            details={"identity": "product_path.public_final_snapshot_artifacts"},
        )
    workspace_record = dict(workspace_envelope)
    event_record = dict(event_envelope)
    workspace = workspace_record.get("workspace")
    events_value = event_record.get("events")
    events = (
        [dict(item) for item in events_value if isinstance(item, dict)]
        if isinstance(events_value, list)
        else []
    )
    session_id = str(product_path.get("session_id") or "")
    workspace_digest = (
        canonical_digest(workspace) if isinstance(workspace, dict) else ""
    )
    event_digest = canonical_digest(events)
    cursors = [item.get("cursor") for item in events]
    event_ids = [str(item.get("event_id") or "") for item in events]
    valid = (
        set(workspace_record)
        == {
            "schema_id",
            "session_id",
            "workspace",
            "workspace_digest",
            "response_binding",
        }
        and workspace_record.get("schema_id") == "aox_public_final_workspace_snapshot@1"
        and workspace_record.get("session_id") == session_id
        and isinstance(workspace, dict)
        and workspace_record.get("workspace_digest") == workspace_digest
        and workspace_digest == product_path.get("public_final_workspace_digest")
        and canonical_json_bytes(workspace_record) + b"\n" == workspace_bytes
        and _sha256(workspace_bytes)
        == product_path.get("public_final_workspace_artifact_digest")
        and workspace_artifact.get("content_digest") == _sha256(workspace_bytes)
        and _public_response_binding_is_valid(
            workspace_record.get("response_binding"),
            receipts=public_api_receipts,
            expected_semantic_digest=workspace_digest,
            expected_route=f"/v3/sessions/{session_id}/workspace",
        )
        and workspace_record.get("response_binding")
        == product_path.get("public_final_workspace_response_binding")
        and product_path.get("public_final_scientific_evidence_digest")
        == canonical_digest(dict(workspace.get("scientific_evidence") or {}))
        and set(event_record)
        == {
            "schema_id",
            "session_id",
            "replay",
            "after_cursor",
            "events",
            "event_count",
            "last_cursor",
            "event_stream_digest",
            "response_binding",
        }
        and event_record.get("schema_id") == "aox_public_final_event_replay@1"
        and event_record.get("session_id") == session_id
        and event_record.get("replay") is True
        and event_record.get("after_cursor") == 0
        and isinstance(events_value, list)
        and len(events) == len(events_value)
        and event_record.get("event_count") == len(events)
        and event_record.get("last_cursor") == max(cursors, default=0)
        and event_record.get("event_stream_digest") == event_digest
        and event_digest == product_path.get("public_final_event_stream_digest")
        and event_record.get("last_cursor")
        == product_path.get("public_final_event_last_cursor")
        and all(
            isinstance(cursor, int) and not isinstance(cursor, bool) and cursor > 0
            for cursor in cursors
        )
        and cursors == sorted(set(cursors))
        and all(event_ids)
        and len(event_ids) == len(set(event_ids))
        and all(item.get("session_id") == session_id for item in events)
        and canonical_json_bytes(event_record) + b"\n" == event_bytes
        and _sha256(event_bytes)
        == product_path.get("public_final_event_replay_artifact_digest")
        and event_artifact.get("content_digest") == _sha256(event_bytes)
        and _public_response_binding_is_valid(
            event_record.get("response_binding"),
            receipts=public_api_receipts,
            expected_semantic_digest=event_digest,
        )
        and (
            _event_replay_route_semantics(
                str(dict(event_record.get("response_binding") or {}).get("route") or "")
            )
            or (None, None)
        )
        == (f"/v3/sessions/{session_id}/events", 0)
        and event_record.get("response_binding")
        == product_path.get("public_final_event_response_binding")
    )
    if not valid:
        raise CutoverEvidenceError(
            "public_final_snapshot_artifact_invalid",
            "final public workspace/event artifacts do not reproduce their Host responses",
            details={"identity": "product_path.public_final_snapshot_artifacts"},
        )
    return dict(workspace), events


def _validate_fault_closure_against_public_snapshots(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    workspace: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> None:
    fault = dict(payload.get("fault_injection") or {})
    closure_artifact_id = str(fault.get("negative_state_closure_artifact_id") or "")
    closure_artifact = next(
        (
            dict(item)
            for item in payload.get("artifacts") or []
            if isinstance(item, dict) and item.get("artifact_id") == closure_artifact_id
        ),
        None,
    )
    try:
        if closure_artifact is None:
            raise ValueError("missing closure artifact")
        closure_bytes = _resolve_artifact_path(
            artifact_root,
            str(closure_artifact.get("relative_path") or ""),
        ).read_bytes()
        document_value = _strict_json_loads(closure_bytes.decode("utf-8"))
        if not isinstance(document_value, dict):
            raise ValueError("closure is not an object")
        document = dict(document_value)
        closure_value = document.get("negative_state_closure")
        if not isinstance(closure_value, dict):
            raise ValueError("negative_state_closure is not an object")
        closure = dict(closure_value)
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "fault_public_snapshot_closure_mismatch",
            "fault negative closure cannot be compared with final public snapshots",
            details={"identity": "fault_injection.negative_state_closure"},
        ) from exc
    public_tasks = sorted(
        (
            {
                "task_id": item.get("task_id"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "assigned_ref": item.get("assigned_ref"),
                "lane_id": item.get("lane_id"),
            }
            for item in dict(workspace.get("task_board") or {}).get("items") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item["task_id"] or ""),
    )
    closure_tasks = sorted(
        (
            {
                "task_id": item.get("task_id"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "assigned_ref": item.get("assigned_ref"),
                "lane_id": item.get("lane_id"),
            }
            for item in closure.get("task_receipts") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item["task_id"] or ""),
    )
    public_reports = sorted(
        (
            {
                "report_id": item.get("report_id"),
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "artifact_id": item.get("artifact_id"),
            }
            for item in workspace.get("reports") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item["report_id"] or ""),
    )
    closure_reports = sorted(
        (
            {
                "report_id": item.get("report_id"),
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "artifact_id": item.get("artifact_id"),
            }
            for item in closure.get("report_states") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item["report_id"] or ""),
    )
    public_drafts = sorted(
        (
            {
                "draft_id": item.get("draft_id"),
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "published_report_id": item.get("published_report_id"),
            }
            for item in workspace.get("report_drafts") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item["draft_id"] or ""),
    )
    closure_drafts = sorted(
        (
            {
                "draft_id": item.get("draft_id"),
                "task_id": item.get("task_id"),
                "status": item.get("status"),
                "published_report_id": item.get("published_report_id"),
            }
            for item in closure.get("draft_states") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item["draft_id"] or ""),
    )
    public_conversation = [
        {
            "message_id": item.get("message_id"),
            "role": item.get("role"),
            "content_digest": _sha256(str(item.get("content") or "").encode("utf-8")),
        }
        for item in workspace.get("conversation") or []
        if isinstance(item, dict)
    ]
    closure_conversation = [
        {
            "message_id": item.get("message_id"),
            "role": item.get("role"),
            "content_digest": item.get("content_digest"),
        }
        for item in closure.get("conversation_receipts") or []
        if isinstance(item, dict)
    ]
    public_events = [
        {
            "event_id": item.get("event_id"),
            "cursor": item.get("cursor"),
            "event_type": item.get("event_type"),
            "actor_ref": item.get("actor_ref"),
            "command_id": item.get("command_id"),
            "payload_digest": canonical_digest(dict(item.get("payload") or {})),
        }
        for item in events
    ]
    closure_events = [
        dict(item)
        for item in closure.get("durable_event_receipts") or []
        if isinstance(item, dict)
    ]
    target_artifact_id = str(fault.get("target_artifact_id") or "")
    public_consumers = sorted(
        (
            {
                "operation_id": item.get("operation_id"),
                "task_id": item.get("task_id"),
                "sdk_module": item.get("sdk_module"),
                "function_name": item.get("function_name"),
                "selected_backend": item.get("selected_backend"),
                "status": item.get("status"),
                "failure_code": item.get("error_code"),
                "operation_identity_digest": item.get("operation_digest"),
            }
            for item in dict(workspace.get("scientific_evidence") or {}).get(
                "operations"
            )
            or []
            if isinstance(item, dict)
            and target_artifact_id in set(item.get("input_artifact_ids") or [])
        ),
        key=lambda item: str(item["operation_id"] or ""),
    )
    closure_consumers = sorted(
        (
            dict(item)
            for item in closure.get("consumer_states") or []
            if isinstance(item, dict)
        ),
        key=lambda item: str(item.get("operation_id") or ""),
    )
    comparisons = (
        (public_tasks, closure_tasks),
        (public_reports, closure_reports),
        (public_drafts, closure_drafts),
        (public_conversation, closure_conversation),
        (public_events, closure_events),
        (public_consumers, closure_consumers),
    )
    if any(public != sealed for public, sealed in comparisons):
        raise CutoverEvidenceError(
            "fault_public_snapshot_closure_mismatch",
            "fault closure omits or invents final public task/report/draft/conversation/event/consumer state",
            details={"identity": "fault_injection.negative_state_closure"},
        )


def _browser_durable_event_is_valid(
    record_value: object,
    *,
    event_type: str,
    session_id: str,
    approval_id: str,
    operation_id: str,
    operation_digest: str,
    continuation_id: str,
) -> bool:
    if not isinstance(record_value, dict):
        return False
    record = dict(record_value)
    payload = dict(record.get("payload") or {})
    expected_payload = (
        {
            "approval_id": approval_id,
            "decision": "approved",
            "actor_ref": record.get("actor_ref"),
        }
        if event_type == "approval.resolved"
        else {
            "approval_id": approval_id,
            "operation_id": operation_id,
            "operation_digest": operation_digest,
            "continuation_id": continuation_id,
            "decision": "approved",
        }
    )
    cursor = record.get("cursor")
    return bool(
        set(record) == _BROWSER_DURABLE_EVENT_KEYS
        and record.get("schema_id") == "aox_browser_durable_event@1"
        and isinstance(cursor, int)
        and not isinstance(cursor, bool)
        and cursor > 0
        and str(record.get("event_id") or "")
        and record.get("session_id") == session_id
        and record.get("event_type") == event_type
        and record.get("schema_version") == "openzyme.v3.event.v1"
        and record.get("visibility") == "public"
        and (
            record.get("actor_ref") is None or isinstance(record.get("actor_ref"), str)
        )
        and (
            record.get("command_id") is None
            or isinstance(record.get("command_id"), str)
        )
        and str(record.get("created_at") or "")
        and payload == expected_payload
        and record.get("payload_digest") == canonical_digest(payload)
    )


def _browser_workspace_snapshots_are_valid(
    browser: Mapping[str, Any],
    *,
    public_api_receipts: Sequence[Mapping[str, Any]],
) -> bool:
    approval_id = str(browser.get("approval_id") or "")
    operation_id = str(browser.get("operation_id") or "")
    operation_digest = str(browser.get("operation_digest") or "")
    pre_value = browser.get("pre_workspace_snapshot")
    post_value = browser.get("post_workspace_snapshot")
    if not isinstance(pre_value, dict) or not isinstance(post_value, dict):
        return False
    pre = dict(pre_value)
    post = dict(post_value)
    pre_pending = [
        dict(item)
        for item in pre.get("pending_approvals") or []
        if isinstance(item, dict)
    ]
    matching_pre = [
        item for item in pre_pending if item.get("approval_id") == approval_id
    ]
    if len(matching_pre) != 1:
        return False
    pre_operation = dict(matching_pre[0].get("operation") or {})
    post_pending_ids = {
        str(item.get("approval_id") or "")
        for item in post.get("pending_approvals") or []
        if isinstance(item, dict)
    }
    post_operations = [
        dict(item)
        for item in dict(post.get("scientific_evidence") or {}).get("operations") or []
        if isinstance(item, dict)
    ]
    matching_post = [
        item for item in post_operations if item.get("operation_id") == operation_id
    ]
    workspace_route = f"/v3/sessions/{browser.get('session_id')}/workspace"
    return bool(
        browser.get("pre_workspace_digest") == canonical_digest(pre)
        and browser.get("post_workspace_digest") == canonical_digest(post)
        and pre_operation.get("operation_id") == operation_id
        and pre_operation.get("operation_digest") == operation_digest
        and matching_pre[0].get("approval_id") == approval_id
        and approval_id not in post_pending_ids
        and len(matching_post) == 1
        and matching_post[0].get("operation_digest") == operation_digest
        and matching_post[0].get("approval_id") == approval_id
        and matching_post[0].get("approval_state") == "approved"
        and matching_post[0].get("status") == browser.get("post_operation_status")
        and _public_response_binding_is_valid(
            browser.get("pre_workspace_response_binding"),
            receipts=public_api_receipts,
            expected_semantic_digest=canonical_digest(pre),
            expected_route=workspace_route,
        )
        and _public_response_binding_is_valid(
            browser.get("post_workspace_response_binding"),
            receipts=public_api_receipts,
            expected_semantic_digest=canonical_digest(post),
            expected_route=workspace_route,
        )
    )


def _browser_event_response_bindings_are_valid(
    browser: Mapping[str, Any],
    *,
    public_api_receipts: Sequence[Mapping[str, Any]],
) -> bool:
    raw_bindings = browser.get("event_response_bindings")
    bindings = (
        [dict(item) for item in raw_bindings if isinstance(item, dict)]
        if isinstance(raw_bindings, list)
        else []
    )
    if not bindings or len(bindings) != len(raw_bindings or []):
        return False
    session_id = str(browser.get("session_id") or "")
    target_records = {
        str(
            dict(browser.get("resolution_event_record") or {}).get("event_id") or ""
        ): dict(browser.get("resolution_event_record") or {}),
        str(
            dict(browser.get("continuation_event_record") or {}).get("event_id") or ""
        ): dict(browser.get("continuation_event_record") or {}),
    }
    matched: dict[str, list[dict[str, Any]]] = {
        event_id: [] for event_id in target_records if event_id
    }
    for binding in bindings:
        records_value = binding.get("event_records")
        records = (
            [dict(item) for item in records_value if isinstance(item, dict)]
            if isinstance(records_value, list)
            else []
        )
        semantics = _event_replay_route_semantics(str(binding.get("route") or ""))
        if (
            set(binding) != _EVENT_RESPONSE_BINDING_KEYS
            or not isinstance(records_value, list)
            or len(records) != len(records_value)
            or binding.get("event_records_digest") != canonical_digest(records)
            or semantics is None
            or semantics[0] != f"/v3/sessions/{session_id}/events"
            or not _public_response_binding_is_valid(
                {key: binding.get(key) for key in _PUBLIC_RESPONSE_BINDING_KEYS},
                receipts=public_api_receipts,
                expected_semantic_digest=canonical_digest(records),
            )
        ):
            return False
        for event in records:
            event_id = str(event.get("event_id") or "")
            if event_id in matched:
                matched[event_id].append(event)
    for event_id, events in matched.items():
        record = target_records[event_id]
        if len(events) != 1:
            return False
        event = events[0]
        if any(
            event.get(key) != record.get(key)
            for key in (
                "event_id",
                "session_id",
                "event_type",
                "schema_version",
                "visibility",
                "actor_ref",
                "command_id",
                "created_at",
                "cursor",
                "payload",
            )
        ):
            return False
        semantics = next(
            _event_replay_route_semantics(str(binding.get("route") or ""))
            for binding in bindings
            if any(
                isinstance(item, dict) and item.get("event_id") == event_id
                for item in binding.get("event_records") or []
            )
        )
        if semantics is None or int(semantics[1]) >= int(record.get("cursor") or 0):
            return False
    return True


def _browser_observation_receipt_is_valid(
    value: object,
    *,
    browser: Mapping[str, Any],
    effective_config: Mapping[str, Any],
    product_path: Mapping[str, Any],
    operation: Mapping[str, Any],
    report: Mapping[str, Any],
    public_api_receipts: Sequence[Mapping[str, Any]],
) -> bool:
    if not isinstance(value, dict):
        return False
    receipt = dict(value)
    entries_value = receipt.get("console_entries")
    entries = (
        [dict(item) for item in entries_value if isinstance(item, dict)]
        if isinstance(entries_value, list)
        else []
    )
    command = dict(receipt.get("devtools_command_receipt") or {})
    page_state = dict(receipt.get("page_state") or {})
    transcript_value = receipt.get("devtools_transcript")
    transcript = (
        [dict(item) for item in transcript_value if isinstance(item, dict)]
        if isinstance(transcript_value, list)
        else []
    )
    driver = dict(effective_config.get("driver") or {})
    screenshot_digest = receipt.get("screenshot_digest")
    screenshot = _validated_browser_png(receipt.get("screenshot_png_base64"))
    expected_page_state = {
        "session_id": product_path.get("session_id"),
        "approval_id": browser.get("approval_id"),
        "operation_id": browser.get("operation_id"),
        "operation_digest": browser.get("operation_digest"),
        "approval_present": False,
        "operation_status": operation.get("status"),
        "final_master_response_id": product_path.get("final_master_response_id"),
        "report_id": report.get("report_id"),
        "report_status": report.get("status"),
        "scientific_evidence_digest": product_path.get(
            "public_final_scientific_evidence_digest"
        ),
        "workspace_digest": product_path.get("public_final_workspace_digest"),
        "workspace_response_binding": product_path.get(
            "public_final_workspace_response_binding"
        ),
        "event_stream_digest": product_path.get("public_final_event_stream_digest"),
        "event_last_cursor": product_path.get("public_final_event_last_cursor"),
        "event_response_binding": product_path.get(
            "public_final_event_response_binding"
        ),
    }
    expected_command_digest = canonical_digest(
        {
            "tool": "chrome_devtools_mcp",
            "command_id": command.get("command_id"),
            "page_target_id": receipt.get("page_target_id"),
            "observation_challenge": receipt.get("observation_challenge"),
            "action": "observe_console_page_state_and_screenshot",
        }
    )
    expected_response_digest = canonical_digest(
        {
            "page_state": page_state,
            "console_entries": entries,
            "application_error_count": receipt.get("application_error_count"),
            "devtools_transcript_digest": canonical_digest(transcript),
            "screenshot_digest": screenshot_digest,
        }
    )
    return bool(
        set(receipt) == _BROWSER_OBSERVATION_RECEIPT_KEYS
        and receipt.get("schema_id") == "aox_browser_observation_receipt@2"
        and receipt.get("observation_mode") == "chrome_devtools_mcp_file_handoff"
        and receipt.get("observation_challenge") == browser.get("observation_challenge")
        and receipt.get("session_id") == browser.get("session_id")
        and receipt.get("approval_id") == browser.get("approval_id")
        and receipt.get("operation_id") == browser.get("operation_id")
        and receipt.get("page_url") == browser.get("page_url")
        and receipt.get("host_process_id") == browser.get("host_process_id")
        and receipt.get("served_ui_dist_digest") == browser.get("served_ui_dist_digest")
        and str(receipt.get("page_target_id") or "")
        and receipt.get("observation_window_seconds")
        == driver.get("browser_completion_hold_seconds")
        and type(receipt.get("host_observation_hold_seconds")) in {int, float}
        and float(receipt.get("host_observation_hold_seconds") or -1)
        >= float(driver.get("browser_completion_hold_seconds") or 0)
        and receipt.get("host_observation_hold_satisfied") is True
        and type(receipt.get("host_observation_submission_timeout_seconds"))
        in {int, float}
        and float(receipt.get("host_observation_submission_timeout_seconds") or 0)
        == float(driver.get("browser_observation_submission_timeout_seconds") or 0)
        and type(receipt.get("host_observation_ready_at_unix_ns")) is int
        and type(receipt.get("host_observation_not_before_unix_ns")) is int
        and type(receipt.get("host_observation_accepted_at_unix_ns")) is int
        and int(receipt.get("host_observation_ready_at_unix_ns") or 0) > 0
        and int(receipt.get("host_observation_not_before_unix_ns") or 0)
        == int(receipt.get("host_observation_ready_at_unix_ns") or 0)
        + int(
            round(
                float(driver.get("browser_completion_hold_seconds") or 0)
                * 1_000_000_000
            )
        )
        and int(receipt.get("host_observation_accepted_at_unix_ns") or 0)
        >= int(receipt.get("host_observation_not_before_unix_ns") or 0)
        and int(receipt.get("host_observation_accepted_at_unix_ns") or 0)
        <= int(receipt.get("host_observation_not_before_unix_ns") or 0)
        + int(
            round(
                float(driver.get("browser_observation_submission_timeout_seconds") or 0)
                * 1_000_000_000
            )
        )
        and isinstance(entries_value, list)
        and len(entries) == len(entries_value)
        and [item.get("sequence") for item in entries]
        == list(range(1, len(entries) + 1))
        and all(
            set(item) == {"sequence", "level", "source", "message_digest"}
            and item.get("level") in {"debug", "info", "log", "warning"}
            and str(item.get("source") or "")
            and _DIGEST_PATTERN.fullmatch(str(item.get("message_digest") or ""))
            is not None
            for item in entries
        )
        and receipt.get("console_entries_digest") == canonical_digest(entries)
        and receipt.get("application_error_count") == 0
        and set(page_state) == _BROWSER_PAGE_STATE_KEYS
        and page_state == expected_page_state
        and receipt.get("page_state_digest") == canonical_digest(page_state)
        and isinstance(transcript_value, list)
        and len(transcript) == len(transcript_value)
        and bool(transcript)
        and [item.get("sequence") for item in transcript]
        == list(range(1, len(transcript) + 1))
        and all(
            set(item)
            == {
                "sequence",
                "tool",
                "method",
                "page_target_id",
                "request_digest",
                "response_digest",
            }
            and item.get("tool") == "chrome_devtools_mcp"
            and item.get("page_target_id") == receipt.get("page_target_id")
            and _DIGEST_PATTERN.fullmatch(str(item.get("request_digest") or ""))
            is not None
            and _DIGEST_PATTERN.fullmatch(str(item.get("response_digest") or ""))
            is not None
            for item in transcript
        )
        and {
            "list_console_messages",
            "evaluate_script",
            "take_screenshot",
        }.issubset({str(item.get("method") or "") for item in transcript})
        and receipt.get("devtools_transcript_digest") == canonical_digest(transcript)
        and _public_response_binding_is_valid(
            page_state.get("workspace_response_binding"),
            receipts=public_api_receipts,
            expected_semantic_digest=str(page_state.get("workspace_digest") or ""),
            expected_route=f"/v3/sessions/{product_path.get('session_id')}/workspace",
        )
        and _public_response_binding_is_valid(
            page_state.get("event_response_binding"),
            receipts=public_api_receipts,
            expected_semantic_digest=str(page_state.get("event_stream_digest") or ""),
        )
        and (
            _event_replay_route_semantics(
                str(
                    dict(page_state.get("event_response_binding") or {}).get("route")
                    or ""
                )
            )
            or (None,)
        )[0]
        == f"/v3/sessions/{product_path.get('session_id')}/events"
        and set(command)
        == {
            "command_id",
            "tool",
            "command_digest",
            "response_digest",
            "page_target_id",
        }
        and str(command.get("command_id") or "")
        and command.get("tool") == "chrome_devtools_mcp"
        and command.get("page_target_id") == receipt.get("page_target_id")
        and _DIGEST_PATTERN.fullmatch(str(command.get("command_digest") or ""))
        is not None
        and command.get("command_digest") == expected_command_digest
        and _DIGEST_PATTERN.fullmatch(str(command.get("response_digest") or ""))
        is not None
        and command.get("response_digest") == expected_response_digest
        and screenshot is not None
        and f"sha256:{hashlib.sha256(screenshot[0]).hexdigest()}" == screenshot_digest
        and receipt.get("screenshot_width") == screenshot[1]
        and receipt.get("screenshot_height") == screenshot[2]
    )


def _validate_known_positive_probe(
    payload: Mapping[str, Any], *, artifact_root: Path
) -> None:
    effective_config = dict(
        dict(dict(payload.get("product_path") or {}).get("launch_receipt") or {}).get(
            "effective_config"
        )
        or {}
    )
    runner_contract_expectations = _runner_contract_expectations_from_config(
        effective_config
    )
    probe = dict(payload.get("known_positive_probe") or {})
    if probe.get("status") != "passed":
        return
    provider_receipts = [
        dict(item)
        for item in probe.get("provider_receipts") or []
        if isinstance(item, dict)
    ]
    toolchain_receipts = [
        dict(item)
        for item in probe.get("toolchain_receipts") or []
        if isinstance(item, dict)
    ]
    checks = [
        dict(item) for item in probe.get("checks") or [] if isinstance(item, dict)
    ]
    operation_roles = dict(probe.get("operation_roles") or {})
    artifact_roles = dict(probe.get("artifact_roles") or {})
    expected_operation_roles = {
        "ncbi_fetch",
        "reference_alignment",
        "hmm_build",
        "uniprot_fetch",
        "candidate_cluster",
        "candidate_alignment",
    }
    expected_artifact_roles = {
        "source_snapshot",
        "ncbi_raw_response",
        "ncbi_fasta",
        "mafft_alignment",
        "hmm_model",
        "uniprot_raw_response",
        "uniprot_fasta",
        "cdhit_clustered_fasta",
        "cdhit_membership",
        "hmmalign_alignment",
    }
    if (
        probe.get("probe_id") != KNOWN_POSITIVE_PROBE_ID
        or len(provider_receipts) != 2
        or len(toolchain_receipts) != 4
        or set(operation_roles) != expected_operation_roles
        or set(artifact_roles) != expected_artifact_roles
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_receipt_missing",
            "a passed probe requires the exact two-provider/four-tool globin receipt schema",
            details={"identity": "known_positive_probe"},
        )
    operations = {
        str(item.get("operation_id") or ""): dict(item)
        for item in payload.get("operations") or []
        if isinstance(item, dict)
    }
    artifacts = {
        str(item.get("artifact_id") or ""): dict(item)
        for item in payload.get("artifacts") or []
        if isinstance(item, dict)
    }
    role_operations = {
        role: operations.get(str(operation_id or ""))
        for role, operation_id in operation_roles.items()
    }
    role_artifacts = {
        role: artifacts.get(str(artifact_id or ""))
        for role, artifact_id in artifact_roles.items()
    }
    declared_artifact_ids = {
        str(item) for item in probe.get("artifact_ids") or [] if str(item)
    }
    provider_by_name = {
        str(item.get("provider") or ""): item for item in provider_receipts
    }
    toolchain_by_tool = {
        str(item.get("tool") or ""): item for item in toolchain_receipts
    }
    prerequisites = dict(
        dict(payload.get("clean_world") or {}).get("allowed_prerequisites") or {}
    )
    if (
        set(provider_by_name) != {"ncbi", "uniprot"}
        or set(toolchain_by_tool) != {"mafft", "hmmbuild", "cd-hit", "hmmalign"}
        or any(operation is None for operation in role_operations.values())
        or any(artifact is None for artifact in role_artifacts.values())
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_identity_missing",
            "known-positive operation or artifact roles do not resolve",
            details={"identity": "known_positive_probe"},
        )
    formal_providers = [
        dict(item)
        for item in payload.get("provider_identities") or []
        if isinstance(item, dict)
    ]
    formal_toolchains = [
        dict(item)
        for item in payload.get("toolchain_identities") or []
        if isinstance(item, dict)
    ]
    formal_provider_record_ids = {
        str(item.get("provider_record_id") or "") for item in formal_providers
    }
    formal_provider_invocation_ids = {
        str(item.get("invocation_id") or "") for item in formal_providers
    }
    formal_provider_operation_ids = {
        str(item.get("operation_id") or "") for item in formal_providers
    }
    formal_toolchain_record_ids = {
        str(item.get("toolchain_record_id") or "") for item in formal_toolchains
    }
    formal_toolchain_job_ids = {
        str(item.get("job_id") or "") for item in formal_toolchains
    }
    formal_toolchain_operation_ids = {
        str(item.get("operation_id") or "") for item in formal_toolchains
    }
    identity_overlap = any(
        str(provider.get("provider_record_id") or "") in formal_provider_record_ids
        or str(provider.get("invocation_id") or "") in formal_provider_invocation_ids
        or str(provider.get("operation_id") or "") in formal_provider_operation_ids
        for provider in provider_receipts
    ) or any(
        str(toolchain.get("toolchain_record_id") or "") in formal_toolchain_record_ids
        or str(toolchain.get("job_id") or "") in formal_toolchain_job_ids
        or str(toolchain.get("operation_id") or "") in formal_toolchain_operation_ids
        for toolchain in toolchain_receipts
    )
    probe_scoped_ids = {
        artifact_id
        for artifact_id, artifact in artifacts.items()
        if artifact.get("scope") == "probe"
    }
    if (
        len(declared_artifact_ids) != len(probe_scoped_ids)
        or declared_artifact_ids != probe_scoped_ids
        or not declared_artifact_ids
        or any(
            artifacts[artifact_id].get("origin")
            != (
                "sandbox_run"
                if artifact_id == str(artifact_roles["source_snapshot"])
                else "operation"
            )
            for artifact_id in declared_artifact_ids
        )
        or any(
            operation.get("scope") != "probe"
            or operation.get("status") != "completed"
            or operation.get("terminal") is not True
            for operation in role_operations.values()
            if operation is not None
        )
        or identity_overlap
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_receipt_invalid",
            "passed known-positive checks must bind independent live provider and HPC receipts",
            details={"identity": "known_positive_probe"},
        )

    def operation_refs(operation: Mapping[str, Any], direction: str) -> dict[str, str]:
        return {
            str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
            for ref in operation.get(direction) or []
            if isinstance(ref, dict)
        }

    def exact_refs(operation_role: str, direction: str) -> dict[str, str]:
        operation = role_operations[operation_role]
        assert operation is not None
        return operation_refs(operation, direction)

    def artifact_ref(artifact_role: str) -> dict[str, str]:
        artifact = role_artifacts[artifact_role]
        assert artifact is not None
        return {
            str(artifact_roles[artifact_role]): str(
                artifact.get("content_digest") or ""
            )
        }

    expected_inputs = {
        "ncbi_fetch": {},
        "reference_alignment": artifact_ref("ncbi_fasta"),
        "hmm_build": artifact_ref("mafft_alignment"),
        "uniprot_fetch": {},
        "candidate_cluster": artifact_ref("uniprot_fasta"),
        "candidate_alignment": {
            **artifact_ref("hmm_model"),
            **artifact_ref("cdhit_clustered_fasta"),
        },
    }
    if any(
        exact_refs(role, "inputs") != expected
        for role, expected in expected_inputs.items()
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_lineage_invalid",
            "globin provider bytes must close through MAFFT/hmmbuild and CD-HIT/HMMalign",
            details={"identity": "known_positive_probe"},
        )

    provider_role_by_name = {"ncbi": "ncbi_fetch", "uniprot": "uniprot_fetch"}
    raw_role_by_name = {
        "ncbi": "ncbi_raw_response",
        "uniprot": "uniprot_raw_response",
    }
    fasta_role_by_name = {"ncbi": "ncbi_fasta", "uniprot": "uniprot_fasta"}
    expected_accessions_by_name = {
        "ncbi": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
        "uniprot": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
    }

    def raw_response_digests(
        artifact: Mapping[str, Any], *, provider_name: str
    ) -> set[str]:
        raw_payload = _strict_json_loads(
            _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_text(encoding="utf-8")
        )
        if (
            not isinstance(raw_payload, dict)
            or raw_payload.get("schema_id") != "provider_raw_http_response_set@1"
            or raw_payload.get("provider") != provider_name
        ):
            return set()
        digests: set[str] = set()
        for response in raw_payload.get("responses") or []:
            if not isinstance(response, dict):
                return set()
            body = base64.b64decode(
                str(response.get("body_base64") or ""), validate=True
            )
            digest = _sha256(body)
            if (
                response.get("body_encoding") != "base64"
                or response.get("body_digest") != digest
                or response.get("size_bytes") != len(body)
            ):
                return set()
            digests.add(digest)
        return digests

    for provider_name, provider in provider_by_name.items():
        role = provider_role_by_name[provider_name]
        operation = role_operations[role]
        raw_artifact = role_artifacts[raw_role_by_name[provider_name]]
        assert operation is not None and raw_artifact is not None
        provider_artifact_ids = {
            str(item) for item in provider.get("artifact_ids") or [] if str(item)
        }
        operation_outputs = exact_refs(role, "outputs")
        parameters = dict(operation.get("parameters") or {})
        try:
            body_digests = raw_response_digests(
                raw_artifact,
                provider_name=provider_name,
            )
        except (
            CutoverEvidenceError,
            OSError,
            UnicodeDecodeError,
            ValueError,
        ):
            body_digests = set()
        if (
            provider.get("status") != "completed"
            or provider.get("cache_hit") is not False
            or not str(provider.get("provider_record_id") or "")
            or not str(provider.get("invocation_id") or "")
            or provider.get("operation_id") != operation_roles[role]
            or _DIGEST_PATTERN.fullmatch(str(provider.get("request_digest") or ""))
            is None
            or provider.get("request_digest") != operation.get("params_digest")
            or _DIGEST_PATTERN.fullmatch(str(provider.get("response_digest") or ""))
            is None
            or provider.get("response_digest") not in body_digests
            or not body_digests
            or provider_artifact_ids != set(operation_outputs)
            or any(
                operation_outputs.get(artifact_id)
                != artifacts[artifact_id].get("content_digest")
                for artifact_id in provider_artifact_ids
            )
            or provider.get("raw_response_artifact_id")
            != artifact_roles[raw_role_by_name[provider_name]]
            or provider.get("parsed_fasta_artifact_id")
            != artifact_roles[fasta_role_by_name[provider_name]]
            or [
                str(value).strip().upper()
                for value in parameters.get("accessions") or []
            ]
            != expected_accessions_by_name[provider_name]
        ):
            raise CutoverEvidenceError(
                "known_positive_probe_provider_invalid",
                "probe provider receipts must seal raw HTTP bodies and the exact globin request",
                details={"identity": f"known_positive_probe.{provider_name}"},
            )

    tool_role_by_name = {
        "mafft": "reference_alignment",
        "hmmbuild": "hmm_build",
        "cd-hit": "candidate_cluster",
        "hmmalign": "candidate_alignment",
    }
    for tool_name, toolchain in toolchain_by_tool.items():
        role = tool_role_by_name[tool_name]
        operation = role_operations[role]
        assert operation is not None
        _validate_attested_toolchain_receipt(
            toolchain,
            operation=operation,
            prerequisites=prerequisites,
            runner_contract_expectations=runner_contract_expectations,
            error_code="known_positive_probe_toolchain_invalid",
        )
        output_ids = {
            str(item) for item in toolchain.get("artifact_ids") or [] if str(item)
        }
        operation_outputs = exact_refs(role, "outputs")
        if (
            toolchain.get("status") != "completed"
            or toolchain.get("operation_id") != operation_roles[role]
            or not str(toolchain.get("toolchain_record_id") or "")
            or not str(toolchain.get("toolchain_id") or "")
            or not str(toolchain.get("job_id") or "")
            or toolchain.get("job_id") != operation.get("backend_run_id")
            or _DIGEST_PATTERN.fullmatch(str(toolchain.get("image_digest") or ""))
            is None
            or output_ids != set(operation_outputs)
            or any(
                operation_outputs.get(artifact_id)
                != artifacts[artifact_id].get("content_digest")
                for artifact_id in output_ids
            )
            or (
                tool_name == "cd-hit"
                and dict(toolchain.get("parameters") or {})
                != {"identity": 1.0, "mode": "protein"}
            )
        ):
            raise CutoverEvidenceError(
                "known_positive_probe_toolchain_invalid",
                "probe tool receipts must bind four real HPC jobs and their sealed outputs",
                details={"identity": f"known_positive_probe.{tool_name}"},
            )

    expected_checks = {
        "ncbi_globin_pair": (
            "provider",
            provider_by_name["ncbi"]["provider_record_id"],
        ),
        "uniprot_globin_pair": (
            "provider",
            provider_by_name["uniprot"]["provider_record_id"],
        ),
        "hpc_mafft": (
            "hpc",
            toolchain_by_tool["mafft"]["toolchain_record_id"],
        ),
        "hpc_hmmbuild": (
            "hpc",
            toolchain_by_tool["hmmbuild"]["toolchain_record_id"],
        ),
        "hpc_cdhit": (
            "hpc",
            toolchain_by_tool["cd-hit"]["toolchain_record_id"],
        ),
        "hpc_hmmalign": (
            "hpc",
            toolchain_by_tool["hmmalign"]["toolchain_record_id"],
        ),
    }
    check_by_id = {str(item.get("check_id") or ""): item for item in checks}
    if set(check_by_id) != set(expected_checks) or any(
        check_by_id[check_id].get("status") != "passed"
        or check_by_id[check_id].get("category") != expected[0]
        or check_by_id[check_id].get("receipt_id") != expected[1]
        for check_id, expected in expected_checks.items()
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_check_invalid",
            "passed probe checks must bind all two provider and four HPC receipts",
            details={"identity": "known_positive_probe.checks"},
        )

    isolation = dict(probe.get("isolation") or {})
    source_snapshot_artifact = role_artifacts["source_snapshot"]
    assert source_snapshot_artifact is not None
    common_session_ids = {
        str(operation.get("session_id") or "")
        for operation in role_operations.values()
        if operation is not None
    }
    common_task_ids = {
        str(operation.get("task_id") or "")
        for operation in role_operations.values()
        if operation is not None
    }
    common_sandbox_run_ids = {
        str(operation.get("sandbox_run_id") or "")
        for operation in role_operations.values()
        if operation is not None
    }
    identity_materials = [
        dict(operation.get("operation_identity_material") or {})
        for operation in role_operations.values()
        if operation is not None
    ]
    common_sandbox_workspace_ids = {
        str(material.get("sandbox_workspace_id") or "")
        for material in identity_materials
    }
    common_source_snapshot_digests = {
        str(material.get("source_snapshot_digest") or "")
        for material in identity_materials
    }
    hpc_workspace_ids = {
        str(
            dict(role_operations[role].get("operation_identity_material") or {}).get(
                "hpc_workspace_id"
            )
            or ""
        )
        for role in (
            "reference_alignment",
            "hmm_build",
            "candidate_cluster",
            "candidate_alignment",
        )
        if role_operations[role] is not None
    }
    if (
        isolation.get("schema_id") != "aox_known_positive_probe_isolation@1"
        or isolation.get("controlled_operation_count") != 6
        or not str(isolation.get("task_finish_ref") or "")
        or common_session_ids != {str(isolation.get("session_id") or "")}
        or common_task_ids != {str(isolation.get("task_id") or "")}
        or common_sandbox_run_ids != {str(isolation.get("sandbox_run_id") or "")}
        or common_sandbox_workspace_ids
        != {str(isolation.get("sandbox_workspace_id") or "")}
        or common_source_snapshot_digests
        != {str(isolation.get("source_snapshot_digest") or "")}
        or hpc_workspace_ids != {str(isolation.get("hpc_workspace_id") or "")}
        or isolation.get("source_snapshot_artifact_id")
        != artifact_roles["source_snapshot"]
        or isolation.get("source_snapshot_artifact_digest")
        != source_snapshot_artifact.get("content_digest")
        or "" in common_session_ids
        or "" in common_task_ids
        or "" in common_sandbox_run_ids
        or "" in common_sandbox_workspace_ids
        or "" in common_source_snapshot_digests
        or "" in hpc_workspace_ids
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_isolation_invalid",
            "probe must remain one-task/one-sandbox/one-source/one-HPC-workspace evidence",
            details={"identity": "known_positive_probe.isolation"},
        )

    try:
        from openzyme_pipeline import aox_similarity

        def artifact_bytes(role: str) -> bytes:
            artifact = role_artifacts[role]
            assert artifact is not None
            return _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_bytes()

        ncbi_sequences = aox_similarity.parse_candidate_fasta(
            artifact_bytes("ncbi_fasta")
        )
        uniprot_sequences = aox_similarity.parse_candidate_fasta(
            artifact_bytes("uniprot_fasta")
        )
        clustered_sequences = aox_similarity.parse_candidate_fasta(
            artifact_bytes("cdhit_clustered_fasta")
        )
        membership = aox_similarity.parse_cdhit_membership_csv(
            artifact_bytes("cdhit_membership")
        )

        def aligned_ids(role: str) -> list[str]:
            return [
                line[1:].strip().split(maxsplit=1)[0]
                for line in artifact_bytes(role).decode("utf-8").splitlines()
                if line.startswith(">")
            ]

        ncbi_ids = [record.sequence_id for record in ncbi_sequences.records]
        uniprot_ids = [record.sequence_id for record in uniprot_sequences.records]
        clustered_ids = [record.sequence_id for record in clustered_sequences.records]
        ncbi_sequence_digests = sorted(
            record.sequence_digest for record in ncbi_sequences.records
        )
        uniprot_sequence_digests = sorted(
            record.sequence_digest for record in uniprot_sequences.records
        )
        identity = dict(probe.get("known_positive_identity") or {})
        scientific_valid = (
            ncbi_ids == list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)
            and uniprot_ids == list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)
            and sorted(clustered_ids) == sorted(uniprot_ids)
            and sorted(row.member_id for row in membership.rows) == sorted(uniprot_ids)
            and len(membership.rows) == 2
            and all(row.is_representative for row in membership.rows)
            and ncbi_sequence_digests == uniprot_sequence_digests
            and aligned_ids("mafft_alignment")
            == list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)
            and aligned_ids("hmmalign_alignment")
            == list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)
            and artifact_bytes("hmm_model").startswith(b"HMMER")
            and identity
            == {
                "ncbi_accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
                "uniprot_accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
                "cross_provider_sequence_digest": canonical_digest(
                    ncbi_sequence_digests
                ),
            }
        )
    except (
        CutoverEvidenceError,
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        scientific_valid = False
    if not scientific_valid:
        raise CutoverEvidenceError(
            "known_positive_probe_scientific_invalid",
            "offline globin identities do not reproduce across both providers and four tools",
            details={"identity": "known_positive_probe.known_positive_identity"},
        )


def _validate_attempt_semantics(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    current_supervision: bool = False,
) -> None:
    if payload.get("schema_id") != ATTEMPT_BUNDLE_SCHEMA_ID_V2:
        raise CutoverEvidenceError(
            "bundle_schema_invalid",
            "attempt bundle schema id is not supported",
            details={"identity": "bundle.schema_id"},
        )
    kind = payload.get("attempt_kind")
    if kind not in {"positive", "fault"}:
        raise CutoverEvidenceError(
            "attempt_kind_invalid",
            "attempt bundle kind must be positive or fault",
            details={"identity": "bundle.attempt_kind"},
        )
    identity = dict(payload.get("identity") or {})
    expected_identity_digest = canonical_digest(
        {key: identity.get(key) for key in _IDENTITY_FIELDS}
    )
    if identity.get("identity_digest") != expected_identity_digest:
        raise CutoverEvidenceError(
            "campaign_identity_digest_mismatch",
            "campaign identity digest does not match its fields",
            details={"identity": "identity.identity_digest"},
        )
    product_path_for_supervision = dict(payload.get("product_path") or {})
    supervision_receipt = product_path_for_supervision.get("attempt_supervision")
    _validate_clean_world_proof(payload)
    _validate_architecture_qualification_evidence(payload)
    micu = dict(payload.get("micu_ledger") or {})
    _validate_ledger_transition(
        dict(micu.get("before") or {}),
        dict(micu.get("after") or {}),
    )
    outcome_for_config = dict(payload.get("scientific_outcome") or {})
    fault_for_config = dict(payload.get("fault_injection") or {})
    supervision_required = (
        kind == "positive" and outcome_for_config.get("cutover_eligible") is True
    ) or (kind == "fault" and fault_for_config.get("reached_target_seam") is True)
    from .aox_host_supervision import HOST_SUPERVISION_RECEIPT_SCHEMA_ID
    from .aox_host_supervision import validate_supervised_host_receipt

    supervised_host_receipt = bool(
        isinstance(supervision_receipt, Mapping)
        and supervision_receipt.get("schema_id")
        == HOST_SUPERVISION_RECEIPT_SCHEMA_ID
    )
    if supervised_host_receipt:
        assert isinstance(supervision_receipt, Mapping)
        authority_slot = dict(
            dict(payload.get("authority") or {}).get("slot") or {}
        )
        clean_world = dict(payload.get("clean_world") or {})
        validate_supervised_host_receipt(
            dict(supervision_receipt),
            launch_id=str(clean_world.get("launch_id") or ""),
            attempt_kind=str(kind),
            session_id=str(authority_slot.get("session_id") or ""),
            task_id=str(authority_slot.get("task_id") or ""),
            root_ref=str(authority_slot.get("root_ref") or ""),
            campaign_id=str(
                dict(payload.get("authority") or {}).get("campaign_id") or ""
            ),
            attempt_authority_id=str(
                supervision_receipt.get("attempt_authority_id") or ""
            ),
            attempt_authority_request_digest=str(
                supervision_receipt.get("attempt_authority_request_digest") or ""
            ),
        )
    if (supervision_required or supervision_receipt is not None) and not (
        supervised_host_receipt
    ):
        from .aox_legacy_supervision_receipt import DEFAULT_KILL_GRACE_SECONDS
        from .aox_legacy_supervision_receipt import DEFAULT_TERM_GRACE_SECONDS
        from .aox_legacy_supervision_receipt import (
            derive_live_attempt_supervision_timeout_seconds,
        )
        from .aox_legacy_supervision_receipt import SUPERVISION_SCHEMA_ID
        from .aox_legacy_supervision_receipt import SUPERVISION_SCHEMA_ID_V1
        from .aox_legacy_supervision_receipt import supervision_contract_digest
        from .aox_legacy_supervision_receipt import (
            validate_attempt_supervision_receipt,
        )

        expected_supervision_contract_digest: str | None = None
        if supervision_required:
            try:
                effective_config = dict(
                    dict(product_path_for_supervision.get("launch_receipt") or {}).get(
                        "effective_config"
                    )
                    or {}
                )
                driver_config = dict(effective_config.get("driver") or {})
                timeout_seconds = derive_live_attempt_supervision_timeout_seconds(
                    attempt_timeout_seconds=driver_config["timeout_seconds"],
                    browser_approval_timeout_seconds=driver_config[
                        "browser_approval_timeout_seconds"
                    ],
                    browser_completion_hold_seconds=driver_config[
                        "browser_completion_hold_seconds"
                    ],
                    browser_observation_submission_timeout_seconds=driver_config[
                        "browser_observation_submission_timeout_seconds"
                    ],
                )
                expected_supervision_contract_digest = supervision_contract_digest(
                    timeout_seconds=timeout_seconds,
                    term_grace_seconds=DEFAULT_TERM_GRACE_SECONDS,
                    kill_grace_seconds=DEFAULT_KILL_GRACE_SECONDS,
                    protocol_schema_id=(
                        SUPERVISION_SCHEMA_ID
                        if current_supervision
                        else SUPERVISION_SCHEMA_ID_V1
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CutoverEvidenceError(
                    "attempt_supervision_contract_mismatch",
                    "process supervision bounds do not derive from effective config",
                    details={"identity": "product_path.attempt_supervision"},
                ) from exc

        if current_supervision and isinstance(supervision_receipt, Mapping):
            attempt_authority_id = supervision_receipt.get("attempt_authority_id")
            attempt_authority_request_digest = supervision_receipt.get(
                "attempt_authority_request_digest"
            )
        else:
            attempt_authority_id = None
            attempt_authority_request_digest = None
        validate_attempt_supervision_receipt(
            supervision_receipt,
            attempt_id=str(payload.get("attempt_id") or ""),
            attempt_kind=str(kind),
            attempt_authority_id=(
                None if attempt_authority_id is None else str(attempt_authority_id)
            ),
            attempt_authority_request_digest=(
                None
                if attempt_authority_request_digest is None
                else str(attempt_authority_request_digest)
            ),
            expected_contract_digest=expected_supervision_contract_digest,
            allow_legacy=not current_supervision,
        )
    if (kind == "positive" and outcome_for_config.get("cutover_eligible") is True) or (
        kind == "fault" and fault_for_config.get("reached_target_seam") is True
    ):
        _validate_effective_config_attestation(payload)
        _validate_delegation_workflow_bindings(payload)
    artifacts = [dict(item) for item in payload.get("artifacts") or []]
    for artifact in artifacts:
        if artifact.get("origin") != "sandbox_run":
            continue
        artifact_id = str(artifact.get("artifact_id") or "")
        provenance = dict(artifact.get("provenance") or {})
        path = _resolve_artifact_path(
            artifact_root,
            str(artifact.get("relative_path") or ""),
        )
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise CutoverEvidenceError(
                "sealed_source_tree_artifact_unreadable",
                "sandbox source-tree evidence bytes are unavailable",
                details={"identity": f"artifact:{artifact_id}:source_tree"},
            ) from exc
        try:
            verify_sealed_source_tree_envelope(
                content,
                expected_source_tree_digest=str(
                    provenance.get("source_snapshot_digest") or ""
                ),
            )
        except CutoverEvidenceError as exc:
            raise CutoverEvidenceError(
                exc.code,
                "sandbox source-tree evidence is not self-verifying",
                details={
                    "identity": f"artifact:{artifact_id}:source_tree",
                    **dict(exc.details),
                },
            ) from exc
    formal_ids = {
        item["artifact_id"] for item in artifacts if item.get("scope") == "formal"
    }
    probe_ids = {
        item["artifact_id"] for item in artifacts if item.get("scope") == "probe"
    }
    if formal_ids & probe_ids:
        raise CutoverEvidenceError(
            "probe_artifact_scope_overlap",
            "known-positive probe artifacts must not enter formal results",
            details={"identity": "artifacts"},
        )
    probe = dict(payload.get("known_positive_probe") or {})
    checks = [
        dict(item) for item in probe.get("checks") or [] if isinstance(item, dict)
    ]
    check_categories = {str(item.get("category") or "") for item in checks}
    if (
        probe.get("status") not in {"passed", "failed"}
        or probe.get("bounded") is not True
        or probe.get("formal_data_isolated") is not True
        or not {"provider", "hpc"}.issubset(check_categories)
        or any(
            item.get("status") not in {"passed", "failed", "unobserved"}
            for item in checks
        )
    ):
        raise CutoverEvidenceError(
            "known_positive_probe_invalid",
            "known-positive evidence must contain bounded, isolated provider and HPC checks",
            details={"identity": "known_positive_probe"},
        )
    referenced_probe_ids = set(str(value) for value in probe.get("artifact_ids") or [])
    if not referenced_probe_ids.issubset(probe_ids):
        raise CutoverEvidenceError(
            "known_positive_probe_artifact_invalid",
            "probe artifact references must resolve only to probe scope",
            details={"identity": "known_positive_probe.artifact_ids"},
        )
    operations = [dict(item) for item in payload.get("operations") or []]
    _validate_known_positive_probe(payload, artifact_root=artifact_root)
    for operation in operations:
        if operation.get("scope") == "formal":
            operation_ids = {
                str(ref.get("artifact_id") or "")
                for key in ("inputs", "outputs")
                for ref in operation.get(key) or []
                if isinstance(ref, dict)
            }
            if operation_ids & probe_ids:
                raise CutoverEvidenceError(
                    "probe_data_entered_formal_operation",
                    "formal operations must not consume or produce probe artifacts",
                    details={
                        "identity": str(operation.get("operation_id") or "operation")
                    },
                )
    product_path = dict(payload.get("product_path") or {})
    outcome = dict(payload.get("scientific_outcome") or {})
    report = dict(payload.get("report") or {})
    if any(
        operation.get("terminal") is not True
        or operation.get("status") not in {"completed", "failed", "recovery_failed"}
        for operation in operations
    ):
        raise CutoverEvidenceError(
            "operation_not_terminal",
            "every recorded controlled operation must have a terminal outcome",
            details={"identity": "operations"},
        )
    tasks = [dict(item) for item in payload.get("tasks") or []]
    eligible_positive = kind == "positive" and outcome.get("cutover_eligible") is True
    if eligible_positive:
        allowed_task_statuses = {"completed", "failed", "cancelled"}
        allowed_business_exits = {
            "agent_explicit",
            "documented_mechanical_transition",
        }
    elif kind == "positive":
        allowed_task_statuses = {
            "todo",
            "in_progress",
            "completed",
            "failed",
            "blocked",
            "cancelled",
        }
        allowed_business_exits = {
            "agent_explicit",
            "current_finish_binding_ambiguous",
            "documented_mechanical_transition",
            "not_terminal",
            "terminal_without_finish",
            "finish_binding_invalid",
        }
    else:
        allowed_task_statuses = {"completed", "failed", "blocked", "cancelled"}
        allowed_business_exits = {
            "agent_explicit",
            "documented_mechanical_transition",
        }
    if any(
        task.get("status") not in allowed_task_statuses
        or task.get("business_exit") not in allowed_business_exits
        for task in tasks
    ):
        raise CutoverEvidenceError(
            "task_business_exit_invalid",
            "attempt tasks do not match the eligibility-specific business-exit contract",
            details={"identity": "tasks"},
        )
    if kind == "positive":
        eligible = eligible_positive
        if eligible:
            _validate_mutation_quiescence_projection(
                product_path,
                allow_formal_failed=False,
            )
            _validate_effective_config_attestation(payload)
            _validate_attempt_hpc_workspace_binding(payload)
            _validate_required_live_chain(payload, artifact_root=artifact_root)
            roles = set(
                str(value) for value in product_path.get("participant_roles") or []
            )
            if (
                product_path.get("entry_message_count") != 1
                or product_path.get("canonical_api_only") is not True
                or not {"researcher", "executor", "reporter"}.issubset(roles)
                or not str(payload.get("final_answer", {}).get("content") or "").strip()
            ):
                raise CutoverEvidenceError(
                    "canonical_product_path_incomplete",
                    "eligible positive attempt must prove one-message canonical multi-role product execution",
                    details={"identity": "product_path"},
                )
            if outcome.get("status") not in {"discovered", "empty"}:
                raise CutoverEvidenceError(
                    "positive_scientific_outcome_invalid",
                    "eligible positive attempt must be an honest discovery or healthy empty result",
                    details={"identity": "scientific_outcome"},
                )
            if not _report_publish_receipt_is_valid(report):
                raise CutoverEvidenceError(
                    "published_report_required",
                    (
                        "eligible positive attempt requires a ready report backed by "
                        "the published draft and its sealed content document"
                    ),
                    details={"identity": "report"},
                )
            if probe.get("status") != "passed" or any(
                item.get("status") != "passed" for item in checks
            ):
                raise CutoverEvidenceError(
                    "known_positive_probe_failed",
                    "eligible positive attempt requires every bounded known-positive check to pass",
                    details={"identity": "known_positive_probe"},
                )
            if any(task.get("status") != "completed" for task in tasks):
                raise CutoverEvidenceError(
                    "positive_task_exit_incomplete",
                    "eligible positive attempt requires every product task to complete explicitly",
                    details={"identity": "tasks"},
                )
            before = dict(micu.get("before") or {})
            after = dict(micu.get("after") or {})
            _validate_micu_attribution(
                before,
                after,
                product_path=product_path,
            )
            if any(
                "fixture_non_cutover" in str(value)
                for value in (
                    payload.get("warnings"),
                    payload.get("degradations"),
                    payload.get("provider_identities"),
                    payload.get("toolchain_identities"),
                )
            ):
                raise CutoverEvidenceError(
                    "fixture_non_cutover",
                    "fixture evidence cannot satisfy a positive live attempt",
                    details={"identity": "attempt"},
                )
        elif (
            outcome.get("status") not in {"failed", "degraded", "incomplete"}
            or report.get("cutover_eligible") is not False
        ):
            raise CutoverEvidenceError(
                "positive_failure_evidence_invalid",
                "a non-eligible positive attempt must preserve an explicit failed outcome",
                details={"identity": "scientific_outcome"},
            )
    else:
        fault = dict(payload.get("fault_injection") or {})
        incomplete_driver_failure = (
            outcome.get("failure_code") == "campaign_runner_failed"
            and fault.get("reached_target_seam") is False
            and fault.get("expected_failure_observed") is False
        )
        controlled_fault = (
            fault.get("fault_id") == FAULT_ARTIFACT_BYTE_FLIP_ID
            and fault.get("reached_target_seam") is True
            and fault.get("expected_failure_observed") is True
            and fault.get("failure_code") == "artifact_blob_digest_mismatch"
            and str(fault.get("negative_state_closure_artifact_id") or "")
        )
        if controlled_fault:
            _validate_mutation_quiescence_projection(
                product_path,
                allow_formal_failed=True,
            )
            _validate_effective_config_attestation(payload)
            _validate_attempt_hpc_workspace_binding(payload)
            launch_receipt = dict(product_path.get("launch_receipt") or {})
            public_api_digest = str(
                launch_receipt.get("public_api_receipt_digest") or ""
            )
            if (
                launch_receipt.get("campaign_attempt_number") != 3
                or launch_receipt.get("approval_mode") != "chrome-once"
                or launch_receipt.get("browser_approval_receipt") is not None
                or launch_receipt.get("browser_observation_receipt") is not None
                or _DIGEST_PATTERN.fullmatch(public_api_digest) is None
            ):
                raise CutoverEvidenceError(
                    "fault_launch_attestation_invalid",
                    "reached fault must be campaign attempt three on the same Chrome launch mode",
                    details={"identity": "product_path.launch_receipt"},
                )
            fault_public_api_receipts = _validate_public_api_receipts(
                product_path,
                expected_digest=public_api_digest,
                payload=payload,
            )
            fault_workspace, fault_events = _validate_public_final_snapshot_artifacts(
                payload,
                artifact_root=artifact_root,
                public_api_receipts=fault_public_api_receipts,
            )
            _validate_fault_closure_against_public_snapshots(
                payload,
                artifact_root=artifact_root,
                workspace=fault_workspace,
                events=fault_events,
            )
            _validate_micu_attribution(
                dict(micu.get("before") or {}),
                dict(micu.get("after") or {}),
                product_path=product_path,
            )
        if (
            not (incomplete_driver_failure or controlled_fault)
            or outcome.get("status") != "failed"
            or outcome.get("cutover_eligible") is not False
            or report.get("cutover_eligible") is not False
        ):
            raise CutoverEvidenceError(
                "fault_not_fail_closed",
                "fault attempt must prove a reached controlled seam and no eligible success",
                details={"identity": "fault_injection"},
            )


def _validate_mutation_quiescence_projection(
    product_path: Mapping[str, Any],
    *,
    allow_formal_failed: bool,
) -> None:
    raw = product_path.get("mutation_quiescence")
    if not isinstance(raw, dict):
        raise CutoverEvidenceError(
            "mutation_quiescence_missing",
            "eligible AOX evidence requires generic Host mutation closure",
            details={"identity": "product_path.mutation_quiescence"},
        )
    projections: dict[str, dict[str, Any]] = {}
    for purpose in ("probe", "formal"):
        candidate = raw.get(purpose)
        if not isinstance(candidate, dict):
            raise CutoverEvidenceError(
                "mutation_quiescence_missing",
                "probe and formal sessions require bounded mutation projections",
                details={"identity": f"product_path.mutation_quiescence.{purpose}"},
            )
        projections[purpose] = dict(candidate)
    for purpose, projection in projections.items():
        identity = f"product_path.mutation_quiescence.{purpose}"
        allowed_states = (
            {"sealed", "failed"}
            if purpose == "formal" and allow_formal_failed
            else {"sealed"}
        )
        writer_counts = projection.get("writer_counts")
        active_writer_counts = projection.get("active_writer_counts")
        if (
            projection.get("schema_version") != "mutation_scope_projection@1"
            or projection.get("scope_kind") != "attempt"
            or projection.get("state") not in allowed_states
            or not isinstance(projection.get("generation"), int)
            or isinstance(projection.get("generation"), bool)
            or int(projection["generation"]) < 1
            or _DIGEST_PATTERN.fullmatch(str(projection.get("policy_digest") or ""))
            is None
            or _DIGEST_PATTERN.fullmatch(str(projection.get("coverage_digest") or ""))
            is None
            or not isinstance(writer_counts, dict)
            or not writer_counts
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 1
                for value in writer_counts.values()
            )
            or active_writer_counts != {}
            or int(writer_counts.get("attempt_driver") or 0) < 1
        ):
            raise CutoverEvidenceError(
                "mutation_quiescence_projection_invalid",
                "mutation closure projection is incomplete or still active",
                details={"identity": identity},
            )
        if projection.get("state") == "failed":
            if (
                not allow_formal_failed
                or not str(projection.get("blocker_code") or "")
                or projection.get("receipt") is not None
            ):
                raise CutoverEvidenceError(
                    "mutation_quiescence_failure_invalid",
                    "failed mutation closure lacks a bounded blocker",
                    details={"identity": identity},
                )
            continue
        receipt = projection.get("receipt")
        if not isinstance(receipt, dict) or (
            not str(receipt.get("receipt_id") or "")
            or not str(receipt.get("snapshot_id") or "")
            or _DIGEST_PATTERN.fullmatch(str(receipt.get("receipt_digest") or ""))
            is None
            or _DIGEST_PATTERN.fullmatch(str(receipt.get("snapshot_digest") or ""))
            is None
            or not str(receipt.get("issued_at") or "")
            or not str(projection.get("sealed_at") or "")
            or projection.get("blocker_code") is not None
        ):
            raise CutoverEvidenceError(
                "mutation_quiescence_receipt_invalid",
                "sealed mutation closure lacks an exact public receipt identity",
                details={"identity": f"{identity}.receipt"},
            )
    if projections["probe"].get("policy_digest") != projections["formal"].get(
        "policy_digest"
    ) or projections["probe"].get("coverage_digest") != projections["formal"].get(
        "coverage_digest"
    ):
        raise CutoverEvidenceError(
            "mutation_quiescence_contract_drift",
            "probe and formal closures use different mutation contracts",
            details={"identity": "product_path.mutation_quiescence"},
        )


def _validate_attempt_hpc_workspace_binding(payload: Mapping[str, Any]) -> None:
    clean_world = dict(payload.get("clean_world") or {})
    label = str(clean_world.get("hpc_workspace_label") or "")
    product_path = dict(payload.get("product_path") or {})
    binding = dict(product_path.get("hpc_workspace_binding") or {})
    observed_ids: set[str] = set()
    for raw_operation in payload.get("operations") or []:
        if not isinstance(raw_operation, dict):
            continue
        operation = dict(raw_operation)
        material = dict(operation.get("operation_identity_material") or {})
        if operation.get("selected_backend") != "hpc":
            continue
        sandbox_workspace_id = str(material.get("sandbox_workspace_id") or "")
        try:
            expected_id = aox_hpc_workspace_id(
                sandbox_workspace_id=sandbox_workspace_id,
                hpc_workspace_label=label,
            )
        except ValueError as exc:
            raise CutoverEvidenceError(
                "hpc_workspace_binding_invalid",
                "attempt HPC workspace binding inputs are malformed",
                details={"identity": str(operation.get("operation_id") or "")},
            ) from exc
        if (
            operation.get("hpc_workspace_id") != expected_id
            or material.get("hpc_workspace_id") != expected_id
        ):
            raise CutoverEvidenceError(
                "hpc_workspace_binding_mismatch",
                "HPC operation identity does not derive from the attempt label and sandbox workspace",
                details={"identity": str(operation.get("operation_id") or "")},
            )
        observed_ids.add(expected_id)
    if (
        not observed_ids
        or set(binding) != {"schema_id", "label", "workspace_ids"}
        or binding.get("schema_id") != AOX_HPC_WORKSPACE_BINDING_CONTRACT_ID
        or binding.get("label") != label
        or binding.get("workspace_ids") != sorted(observed_ids)
    ):
        raise CutoverEvidenceError(
            "hpc_workspace_binding_invalid",
            "attempt must seal the exact authoritative HPC workspace identity set",
            details={"identity": "product_path.hpc_workspace_binding"},
        )


def _verify_required_shape(
    payload: Mapping[str, Any], issues: list[VerificationIssue]
) -> bool:
    required = {
        "schema_id",
        "attempt_id",
        "attempt_kind",
        "identity",
        "clean_world",
        "micu_ledger",
        "known_positive_probe",
        "product_path",
        "approvals",
        "operations",
        "tasks",
        "artifacts",
        "report",
        "final_answer",
        "scientific_outcome",
        "provider_identities",
        "engine_invocations",
        "toolchain_identities",
        "scientific_checks",
        "warnings",
        "degradations",
        "fault_injection",
        "sealed_at",
    }
    missing = sorted(required - set(payload))
    for key in missing:
        issues.append(
            VerificationIssue(
                code="bundle_field_missing",
                identity=f"bundle.{key}",
                message="required attempt bundle field is missing",
            )
        )
    object_fields = {
        "identity",
        "clean_world",
        "micu_ledger",
        "known_positive_probe",
        "product_path",
        "report",
        "final_answer",
        "scientific_checks",
        "scientific_outcome",
    }
    collection_fields = {
        "provider_identities",
        "engine_invocations",
        "toolchain_identities",
        "approvals",
        "operations",
        "tasks",
        "artifacts",
    }
    shape_valid = not missing
    for key in sorted(object_fields & set(payload)):
        if not isinstance(payload.get(key), dict):
            shape_valid = False
            issues.append(
                VerificationIssue(
                    code="bundle_field_type_invalid",
                    identity=f"bundle.{key}",
                    message="bundle field must be an object",
                )
            )
    for key in sorted(collection_fields & set(payload)):
        value = payload.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            shape_valid = False
            issues.append(
                VerificationIssue(
                    code="bundle_field_type_invalid",
                    identity=f"bundle.{key}",
                    message="bundle field must be an array of objects",
                )
            )
    for key in ("warnings", "degradations"):
        value = payload.get(key)
        if key in payload and (
            not isinstance(value, list)
            or not all(isinstance(item, str) for item in value)
        ):
            shape_valid = False
            issues.append(
                VerificationIssue(
                    code="bundle_field_type_invalid",
                    identity=f"bundle.{key}",
                    message="bundle field must be an array of strings",
                )
            )
    if payload.get("fault_injection") is not None and not isinstance(
        payload.get("fault_injection"), dict
    ):
        shape_valid = False
        issues.append(
            VerificationIssue(
                code="bundle_field_type_invalid",
                identity="bundle.fault_injection",
                message="fault injection must be an object or null",
            )
        )
    for key in ("schema_id", "attempt_id", "attempt_kind", "sealed_at"):
        if key in payload and not isinstance(payload.get(key), str):
            shape_valid = False
            issues.append(
                VerificationIssue(
                    code="bundle_field_type_invalid",
                    identity=f"bundle.{key}",
                    message="bundle identity field must be text",
                )
            )
    return shape_valid


def _verify_artifacts(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    issues: list[VerificationIssue],
) -> dict[str, dict[str, Any]]:
    artifact_map: dict[str, dict[str, Any]] = {}
    for raw in payload.get("artifacts") or []:
        if not isinstance(raw, dict):
            issues.append(
                VerificationIssue(
                    code="artifact_record_invalid",
                    identity="artifacts",
                    message="artifact record is not an object",
                )
            )
            continue
        record = dict(raw)
        artifact_id = str(record.get("artifact_id") or "")
        if not artifact_id or artifact_id in artifact_map:
            issues.append(
                VerificationIssue(
                    code="artifact_identity_invalid",
                    identity=artifact_id or "artifacts",
                    message="artifact id is missing or duplicated",
                )
            )
            continue
        artifact_map[artifact_id] = record
        provenance = dict(record.get("provenance") or {})
        provenance_digest = canonical_digest(provenance)
        if record.get("provenance_digest") != provenance_digest:
            issues.append(
                VerificationIssue(
                    code="artifact_provenance_digest_mismatch",
                    identity=f"artifact:{artifact_id}:provenance",
                    message="artifact provenance digest does not match",
                    expected=record.get("provenance_digest"),
                    actual=provenance_digest,
                )
            )
        try:
            path = _resolve_artifact_path(
                artifact_root,
                str(record.get("relative_path") or ""),
            )
            content = path.read_bytes()
        except (CutoverEvidenceError, OSError) as exc:
            issues.append(
                VerificationIssue(
                    code="artifact_unreadable",
                    identity=f"artifact:{artifact_id}",
                    message=f"artifact bytes are unavailable: {type(exc).__name__}",
                )
            )
            continue
        try:
            decoded_content = content.decode("utf-8")
        except UnicodeDecodeError:
            decoded_content = None
        if decoded_content is not None:
            try:
                _assert_public_safe(
                    decoded_content,
                    identity=f"artifact:{artifact_id}:content",
                )
            except CutoverEvidenceError as exc:
                issues.append(
                    VerificationIssue(
                        code=exc.code,
                        identity=str(
                            exc.details.get("identity")
                            or f"artifact:{artifact_id}:content"
                        ),
                        message="text artifact contains non-public evidence",
                    )
                )
        digest = _sha256(content)
        if record.get("content_digest") != digest:
            issues.append(
                VerificationIssue(
                    code="artifact_content_digest_mismatch",
                    identity=f"artifact:{artifact_id}:content",
                    message="sealed artifact bytes do not match",
                    expected=record.get("content_digest"),
                    actual=digest,
                )
            )
        if record.get("size_bytes") != len(content):
            issues.append(
                VerificationIssue(
                    code="artifact_size_mismatch",
                    identity=f"artifact:{artifact_id}:size",
                    message="sealed artifact size does not match",
                    expected=record.get("size_bytes"),
                    actual=len(content),
                )
            )
        typed_empty_raw = record.get("registration_validation")
        is_zero_sequence = record.get("kind") == "sequence" and content == b""
        if is_zero_sequence:
            receipt = dict(typed_empty_raw) if isinstance(typed_empty_raw, dict) else {}
            format_value = str(receipt.get("format") or "").lower()
            reason = receipt.get("empty_result_reason")
            derivation = receipt.get("derivation_contract_id")
            reconstructed_validation = {
                "status": "passed",
                "format": format_value,
                "required_columns": [],
                "validation_profile": "fasta_zero_records@1",
                "empty_result_reason": reason,
                "derivation_contract_id": derivation,
            }
            outcome_reason = dict(payload.get("scientific_outcome") or {}).get(
                "empty_result_reason"
            )
            if (
                set(receipt) != _TYPED_EMPTY_ARTIFACT_VALIDATION_KEYS
                or receipt.get("schema_id") != TYPED_EMPTY_ARTIFACT_VALIDATION_SCHEMA_ID
                or receipt.get("kind") != "sequence"
                or format_value not in {"fa", "faa", "fasta"}
                or receipt.get("validation_profile") != "fasta_zero_records@1"
                or not isinstance(reason, str)
                or _EMPTY_RESULT_REASON_PATTERN.fullmatch(reason) is None
                or not isinstance(derivation, str)
                or _DERIVATION_CONTRACT_PATTERN.fullmatch(derivation) is None
                or receipt.get("catalog_validation_digest")
                != canonical_digest(reconstructed_validation)
                or reason != outcome_reason
            ):
                issues.append(
                    VerificationIssue(
                        code="typed_empty_artifact_validation_invalid",
                        identity=f"artifact:{artifact_id}:registration_validation",
                        message="zero-record FASTA lacks a reproducible strict registration receipt",
                    )
                )
        elif typed_empty_raw is not None:
            issues.append(
                VerificationIssue(
                    code="typed_empty_artifact_validation_invalid",
                    identity=f"artifact:{artifact_id}:registration_validation",
                    message="typed-empty registration receipt is attached to a nonempty or non-sequence artifact",
                )
            )
        if record.get("origin") == "sandbox_run":
            if record.get("kind") != "code":
                issues.append(
                    VerificationIssue(
                        code="sealed_source_tree_kind_invalid",
                        identity=f"artifact:{artifact_id}:kind",
                        message="sandbox source-tree evidence must retain kind=code",
                    )
                )
            try:
                verify_sealed_source_tree_envelope(
                    content,
                    expected_source_tree_digest=str(
                        provenance.get("source_snapshot_digest") or ""
                    ),
                )
            except CutoverEvidenceError as exc:
                issues.append(
                    VerificationIssue(
                        code=exc.code,
                        identity=f"artifact:{artifact_id}:source_tree",
                        message="sandbox source-tree envelope is not self-verifying",
                        expected=exc.details.get("expected"),
                        actual=exc.details.get("actual"),
                    )
                )
    return artifact_map


def _verify_fixed_deliverable_artifact_contracts(
    payload: Mapping[str, Any],
    *,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    by_path: dict[str, list[tuple[str, Mapping[str, Any]]]] = {
        path: [] for path in AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS
    }
    for artifact_id, record in artifact_map.items():
        provenance = dict(record.get("provenance") or {})
        deliverable_path = str(record.get("deliverable_path") or "")
        catalog_path = str(provenance.get("catalog_relative_path") or "")
        recognized_paths = {
            path
            for path in (deliverable_path, catalog_path)
            if path in AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS
        }
        if not recognized_paths:
            continue
        if len(recognized_paths) != 1:
            issues.append(
                VerificationIssue(
                    code="final_deliverable_artifact_contract_mismatch",
                    identity=f"artifact:{artifact_id}:deliverable_path",
                    message="deliverable and catalog paths disagree",
                )
            )
            continue
        path = next(iter(recognized_paths))
        by_path[path].append((artifact_id, record))
        expected_kind, expected_format = AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS[path]
        if (
            deliverable_path != path
            or catalog_path != path
            or record.get("deliverable_artifact_contract_id")
            != AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
            or provenance.get("deliverable_artifact_contract_id")
            != AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
            or record.get("kind") != expected_kind
            or record.get("format") != expected_format
        ):
            issues.append(
                VerificationIssue(
                    code="final_deliverable_artifact_contract_mismatch",
                    identity=f"artifact:{artifact_id}:wire_contract",
                    message=(
                        "normalized AOX deliverable does not retain its exact "
                        "path, kind, format, and versioned artifact contract"
                    ),
                    expected={
                        "deliverable_path": path,
                        "kind": expected_kind,
                        "format": expected_format,
                        "contract_id": (AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID),
                    },
                    actual={
                        "deliverable_path": deliverable_path,
                        "catalog_relative_path": catalog_path,
                        "kind": record.get("kind"),
                        "format": record.get("format"),
                        "contract_id": record.get("deliverable_artifact_contract_id"),
                        "provenance_contract_id": provenance.get(
                            "deliverable_artifact_contract_id"
                        ),
                    },
                )
            )
    if (
        payload.get("attempt_kind") == "positive"
        and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
        is True
    ):
        invalid_counts = {
            path: len(records) for path, records in by_path.items() if len(records) != 1
        }
        if invalid_counts:
            issues.append(
                VerificationIssue(
                    code="final_deliverable_artifact_contract_incomplete",
                    identity="artifacts.final_deliverables",
                    message=(
                        "positive evidence must contain exactly one typed artifact "
                        "for every fixed AOX deliverable path"
                    ),
                    expected={path: 1 for path in sorted(invalid_counts)},
                    actual={
                        path: invalid_counts[path] for path in sorted(invalid_counts)
                    },
                )
            )


def _verify_unified_final_deliverables(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    from openzyme_pipeline import aox_candidate
    from openzyme_pipeline import aox_finalization

    from .aox_final_deliverable_validation import (
        S15_AOX_HMM_FIXED_DELIVERABLES,
    )
    from .aox_final_deliverable_validation import (
        validate_aox_final_artifacts,
    )
    from .aox_bundle_finalizer import (
        required_aox_conditional_output_paths,
    )

    receipt_value = dict(payload.get("scientific_checks") or {}).get(
        "finalization_receipt"
    )
    if not isinstance(receipt_value, dict):
        # Historical sealed bundles remain independently verifiable. Current
        # formal runs cannot reach collection without the runtime receipt gate;
        # when the new receipt is present, this verifier always recomputes it.
        return
    receipt = dict(receipt_value)
    receipt_without_digest = dict(receipt)
    declared_receipt_digest = receipt_without_digest.pop("receipt_digest", None)
    control = payload.get("scientific_attempt_control")
    control_payload = control if isinstance(control, dict) else {}
    attempt = dict(control_payload.get("attempt") or {})
    selection = dict(control_payload.get("selection") or {})
    validation_metadata = receipt.get("validation_metadata")
    receipt_artifacts = receipt.get("artifacts")
    if (
        receipt.get("schema_id") != aox_finalization.FINALIZATION_RECEIPT_SCHEMA_ID
        or receipt.get("status") != "passed"
        or declared_receipt_digest != canonical_digest(receipt_without_digest)
        or receipt.get("attempt_id") != attempt.get("attempt_id")
        or receipt.get("selection_id") != selection.get("selection_id")
        or receipt.get("execution_task_id") != attempt.get("task_id")
        or receipt.get("agent_id") != selection.get("actor_ref")
        or not isinstance(validation_metadata, dict)
        or set(validation_metadata) != S15_AOX_HMM_FIXED_DELIVERABLES
        or not all(
            isinstance(metadata, dict) for metadata in validation_metadata.values()
        )
        or not isinstance(receipt_artifacts, list)
    ):
        issues.append(
            VerificationIssue(
                code="aox_finalization_receipt_invalid",
                identity="scientific_checks.finalization_receipt",
                message=(
                    "atomic finalization receipt failed its closed identity "
                    "or source-bound task check"
                ),
            )
        )
        return

    records_by_path: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for artifact_id, record in artifact_map.items():
        provenance = dict(record.get("provenance") or {})
        path = str(
            record.get("deliverable_path")
            or provenance.get("catalog_relative_path")
            or ""
        )
        if path not in S15_AOX_HMM_FIXED_DELIVERABLES:
            continue
        if path in records_by_path:
            issues.append(
                VerificationIssue(
                    code="aox_finalization_artifact_cardinality_invalid",
                    identity=f"artifact:{path}",
                    message=(
                        "atomic finalization evidence contains duplicate "
                        "deliverable paths"
                    ),
                )
            )
            return
        records_by_path[path] = (artifact_id, record)

    artifact_text: dict[str, str] = {}
    unreadable = False
    for path, (_, record) in records_by_path.items():
        try:
            content = _resolve_artifact_path(
                artifact_root,
                str(record.get("relative_path") or ""),
            ).read_bytes()
            artifact_text[path] = content.decode("utf-8")
        except (CutoverEvidenceError, OSError, UnicodeDecodeError):
            unreadable = True
            issues.append(
                VerificationIssue(
                    code="aox_finalization_artifact_unreadable",
                    identity=f"artifact:{path}",
                    message=("atomic finalization deliverable is not readable UTF-8"),
                )
            )
    if unreadable:
        return
    validation = validate_aox_final_artifacts(
        set(records_by_path),
        artifact_text,
        {str(path): dict(metadata) for path, metadata in validation_metadata.items()},
    )
    if validation.get("passed") is not True:
        earliest = validation.get("earliest_error")
        issues.append(
            VerificationIssue(
                code=str(
                    validation.get("earliest_error_code")
                    or "aox_final_deliverable_validation_failed"
                ),
                identity="scientific_checks.finalization_receipt.validation",
                message=(
                    "unified offline validator preserved the earliest typed "
                    f"cause: {earliest!r}"
                ),
                expected=True,
                actual=False,
            )
        )
        return
    if receipt.get("validation") != validation:
        issues.append(
            VerificationIssue(
                code="aox_finalization_receipt_validation_drift",
                identity="scientific_checks.finalization_receipt.validation",
                message=(
                    "offline validator result differs from the live/eval receipt result"
                ),
                expected=canonical_digest(receipt.get("validation")),
                actual=canonical_digest(validation),
            )
        )

    expected_refs = {
        (
            path,
            artifact_id,
            str(record.get("content_digest") or ""),
        )
        for path, (artifact_id, record) in records_by_path.items()
    }
    observed_refs = {
        (
            str(item.get("relative_path") or ""),
            str(item.get("artifact_id") or ""),
            str(item.get("content_digest") or ""),
        )
        for item in receipt_artifacts
        if isinstance(item, dict)
    }
    if observed_refs != expected_refs:
        issues.append(
            VerificationIssue(
                code="aox_finalization_receipt_artifact_drift",
                identity="scientific_checks.finalization_receipt.artifacts",
                message=(
                    "atomic finalization receipt does not bind the sealed "
                    "17-deliverable evidence set"
                ),
            )
        )
    calculations = receipt.get("calculation_receipts")
    if not isinstance(calculations, list) or not all(
        isinstance(item, dict) for item in calculations
    ):
        issues.append(
            VerificationIssue(
                code="aox_finalization_receipt_calculation_invalid",
                identity=(
                    "scientific_checks.finalization_receipt.calculation_receipts"
                ),
                message="atomic finalization receipt lacks calculation receipts",
            )
        )
        return
    calculations_by_id = {
        str(item.get("calculation_id") or ""): dict(item) for item in calculations
    }
    candidate = calculations_by_id.get(aox_candidate.CALCULATION_ID)
    finalizer = calculations_by_id.get(aox_finalization.FINALIZATION_CALCULATION_ID)
    receipt_refs_by_path = {
        str(item.get("relative_path") or ""): dict(item)
        for item in receipt_artifacts
        if isinstance(item, dict)
    }
    conditional_ids = set(calculations_by_id).intersection(
        {
            aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID,
            aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
            aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID,
        }
    )
    try:
        if (
            len(calculations_by_id) != len(calculations)
            or candidate is None
            or finalizer != aox_finalization.finalization_calculation_receipt()
        ):
            raise ValueError("calculation receipt cardinality drifted")
        aox_candidate.validate_calculation_receipt(candidate)
        expected_conditional = required_aox_conditional_output_paths(validation)
        if conditional_ids != set(expected_conditional):
            raise ValueError("conditional calculation set drifted")
        if (
            candidate.get("target_input_digest")
            != receipt_refs_by_path["aox_hmm/target.fasta"].get("content_digest")
            or candidate.get("scoring_input_digest")
            != receipt_refs_by_path["aox_hmm/scored_ref_plus_hits.csv"].get(
                "content_digest"
            )
            or candidate.get("output_digest")
            != receipt_refs_by_path["aox_hmm/AOX_candidates.fasta"].get(
                "content_digest"
            )
            or candidate.get("candidate_count") != validation.get("candidate_count")
        ):
            raise ValueError("candidate receipt artifact binding drifted")
        for calculation_id, path in expected_conditional.items():
            calculation_receipt = calculations_by_id[calculation_id]
            aox_finalization.validate_conditional_receipt(calculation_receipt)
            if calculation_receipt.get("output_digest") != receipt_refs_by_path[
                path
            ].get("content_digest"):
                raise ValueError("conditional output binding drifted")
            source_calculation = calculation_receipt.get("source_calculation")
            if (
                calculation_id == aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID
                and source_calculation != candidate
            ):
                raise ValueError("empty membership source drifted")
            if (
                calculation_id == aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                and isinstance(source_calculation, dict)
                and source_calculation.get("output_digest")
                != receipt_refs_by_path[
                    "aox_hmm/hmmer_score_filtered_accessions.csv"
                ].get("content_digest")
            ):
                raise ValueError("upstream empty source drifted")
            if (
                calculation_id
                == aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID
                and isinstance(source_calculation, dict)
            ):
                source_id = source_calculation.get("calculation_id")
                if (
                    source_id == aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                    and source_calculation
                    != calculations_by_id.get(
                        aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                    )
                ) or (
                    source_id != aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID
                    and source_calculation.get("output_digest")
                    != receipt_refs_by_path["aox_hmm/target.fasta"].get(
                        "content_digest"
                    )
                ):
                    raise ValueError("reference-only source drifted")
    except Exception:
        issues.append(
            VerificationIssue(
                code="aox_finalization_receipt_calculation_invalid",
                identity=(
                    "scientific_checks.finalization_receipt.calculation_receipts"
                ),
                message=(
                    "atomic finalization receipt contains a drifted or "
                    "uninstalled calculation identity"
                ),
            )
        )


def _verify_record_digests(
    payload: Mapping[str, Any], *, issues: list[VerificationIssue]
) -> None:
    for collection in (
        "provider_identities",
        "engine_invocations",
        "toolchain_identities",
        "approvals",
        "operations",
        "tasks",
    ):
        for index, raw in enumerate(payload.get(collection) or []):
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            expected = record.get("record_digest")
            actual = canonical_digest(
                {key: value for key, value in record.items() if key != "record_digest"}
            )
            if expected != actual:
                issues.append(
                    VerificationIssue(
                        code="record_digest_mismatch",
                        identity=f"{collection}[{index}]",
                        message="canonical record digest does not match",
                        expected=expected,
                        actual=actual,
                    )
                )
    for key in ("known_positive_probe", "report"):
        record = dict(payload.get(key) or {})
        expected = record.get("record_digest")
        actual = canonical_digest(
            {
                item_key: value
                for item_key, value in record.items()
                if item_key != "record_digest"
            }
        )
        if expected != actual:
            issues.append(
                VerificationIssue(
                    code="record_digest_mismatch",
                    identity=key,
                    message="canonical record digest does not match",
                    expected=expected,
                    actual=actual,
                )
            )
    final_answer = dict(payload.get("final_answer") or {})
    actual_answer_digest = _sha256(
        str(final_answer.get("content") or "").encode("utf-8")
    )
    if final_answer.get("content_digest") != actual_answer_digest:
        issues.append(
            VerificationIssue(
                code="final_answer_digest_mismatch",
                identity="final_answer.content",
                message="final answer digest does not match",
                expected=final_answer.get("content_digest"),
                actual=actual_answer_digest,
            )
        )


def _verify_lineage(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    operation_outputs: set[str] = set()
    operation_identity_digests: dict[str, str] = {}
    seen_operation_ids: set[str] = set()
    fault = dict(payload.get("fault_injection") or {})
    for operation in payload.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        operation_id = str(operation.get("operation_id") or "")
        if not operation_id or operation_id in seen_operation_ids:
            issues.append(
                VerificationIssue(
                    code="operation_identity_invalid",
                    identity=f"operation:{operation_id or 'missing'}",
                    message="operation ids must be unique and non-empty",
                )
            )
        seen_operation_ids.add(operation_id)
        identity_digest = str(operation.get("operation_identity_digest") or "")
        operation_identity_digests[operation_id] = identity_digest
        try:
            _validate_operation_identity(operation)
        except CutoverEvidenceError as exc:
            issues.append(
                VerificationIssue(
                    code=exc.code,
                    identity=f"operation:{operation_id}",
                    message="operation identity does not match its canonical owner material",
                )
            )
        for direction in ("inputs", "outputs"):
            for ref in operation.get(direction) or []:
                if not isinstance(ref, dict):
                    continue
                artifact_id = str(ref.get("artifact_id") or "")
                artifact = artifact_map.get(artifact_id)
                if artifact is None:
                    issues.append(
                        VerificationIssue(
                            code="lineage_artifact_missing",
                            identity=f"operation:{operation_id}:{direction}:{artifact_id}",
                            message="operation lineage references an unknown artifact",
                        )
                    )
                    continue
                expected_prefault_reference = (
                    payload.get("attempt_kind") == "fault"
                    and fault.get("reached_target_seam") is True
                    and artifact_id == fault.get("target_artifact_id")
                    and ref.get("content_digest") == fault.get("before_digest")
                    and artifact.get("content_digest") == fault.get("after_digest")
                )
                if (
                    ref.get("content_digest") != artifact.get("content_digest")
                    and not expected_prefault_reference
                ):
                    issues.append(
                        VerificationIssue(
                            code="lineage_digest_mismatch",
                            identity=f"operation:{operation_id}:{direction}:{artifact_id}",
                            message="operation lineage digest differs from sealed artifact",
                            expected=ref.get("content_digest"),
                            actual=artifact.get("content_digest"),
                        )
                    )
                if direction == "outputs":
                    operation_outputs.add(artifact_id)
    for approval in payload.get("approvals") or []:
        if not isinstance(approval, dict):
            continue
        operation_id = str(approval.get("operation_id") or "")
        expected = operation_identity_digests.get(operation_id)
        if (
            approval.get("decision") != "approved"
            or expected is None
            or next(
                (
                    item.get("canonical_ref_kind")
                    for item in payload.get("operations") or []
                    if isinstance(item, dict)
                    and item.get("operation_id") == operation_id
                ),
                None,
            )
            != "controlled_operation"
            or approval.get("operation_identity_digest") != expected
        ):
            issues.append(
                VerificationIssue(
                    code="approval_operation_identity_mismatch",
                    identity=f"approval:{approval.get('approval_id')}",
                    message="approval did not resume the same controlled operation identity",
                    expected=expected,
                    actual=approval.get("operation_identity_digest"),
                )
            )
    for artifact_id, artifact in artifact_map.items():
        if (
            artifact.get("origin") == "operation"
            and artifact_id not in operation_outputs
        ):
            issues.append(
                VerificationIssue(
                    code="artifact_lineage_unclosed",
                    identity=f"artifact:{artifact_id}",
                    message="operation-produced artifact is not linked from an operation output",
                )
            )
        elif artifact.get("origin") == "sandbox_run":
            provenance = dict(artifact.get("provenance") or {})
            matching_operations = [
                operation
                for operation in payload.get("operations") or []
                if isinstance(operation, dict)
                and operation.get("canonical_ref_kind") == "controlled_operation"
                and operation.get("source_snapshot_artifact_id") == artifact_id
            ]
            sandbox_run_ids = {
                str(operation.get("sandbox_run_id") or "")
                for operation in matching_operations
            }
            source_snapshot_digests = {
                str(operation.get("source_snapshot_digest") or "")
                for operation in matching_operations
            }
            if (
                provenance.get("producer") != "sandbox_source_snapshot"
                or sandbox_run_ids != {str(provenance.get("sandbox_run_id") or "")}
                or source_snapshot_digests
                != {str(provenance.get("source_snapshot_digest") or "")}
                or "" in sandbox_run_ids
                or "" in source_snapshot_digests
            ):
                issues.append(
                    VerificationIssue(
                        code="sandbox_source_snapshot_lineage_invalid",
                        identity=f"artifact:{artifact_id}",
                        message=(
                            "sandbox-run source snapshot must bind every consuming "
                            "controlled operation to one run and source-tree digest"
                        ),
                    )
                )
    report = dict(payload.get("report") or {})
    for artifact_id in report.get("artifact_ids") or []:
        artifact = artifact_map.get(str(artifact_id))
        if artifact is None or artifact.get("scope") != "formal":
            issues.append(
                VerificationIssue(
                    code="report_artifact_ref_invalid",
                    identity=f"report:{artifact_id}",
                    message="report references a missing or non-formal artifact",
                )
            )
    report_artifact_id = str(report.get("content_artifact_id") or "")
    report_artifact = artifact_map.get(report_artifact_id)
    if report_artifact is None:
        issues.append(
            VerificationIssue(
                code="report_content_missing",
                identity="report.content_artifact_id",
                message="report content artifact is missing",
            )
        )
    elif (
        report_artifact.get("scope") != "formal"
        or report_artifact.get("origin") != "report"
    ):
        issues.append(
            VerificationIssue(
                code="report_content_scope_invalid",
                identity="report.content_artifact_id",
                message="report content must be a formal report-origin artifact",
            )
        )
    elif report.get("content_digest") != report_artifact.get("content_digest"):
        issues.append(
            VerificationIssue(
                code="report_content_digest_mismatch",
                identity=f"report:{report.get('report_id')}:content",
                message="report digest differs from its sealed content artifact",
                expected=report.get("content_digest"),
                actual=report_artifact.get("content_digest"),
            )
        )
    elif (
        payload.get("attempt_kind") == "positive"
        and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
        is True
    ):
        provenance = dict(report_artifact.get("provenance") or {})
        content_document = report.get("content_document_record")
        document_payload = (
            content_document.get("payload")
            if isinstance(content_document, dict)
            else None
        )
        markdown = (
            document_payload.get("markdown")
            if isinstance(document_payload, dict)
            else None
        )
        try:
            sealed_content = _resolve_artifact_path(
                artifact_root,
                str(report_artifact.get("relative_path") or ""),
            ).read_bytes()
        except (CutoverEvidenceError, OSError):
            sealed_content = None
        if (
            not _report_publish_receipt_is_valid(report)
            or not isinstance(markdown, str)
            or sealed_content != markdown.encode("utf-8")
            or provenance.get("report_id") != report.get("report_id")
            or provenance.get("draft_id") != report.get("draft_id")
            or provenance.get("content_ref") != report.get("content_ref")
            or provenance.get("content_document_digest")
            != report.get("content_document_digest")
            or provenance.get("draft_published") is not True
        ):
            issues.append(
                VerificationIssue(
                    code="report_publish_lineage_invalid",
                    identity=f"report:{report.get('report_id')}:publication",
                    message=(
                        "sealed report bytes must resolve to the published draft "
                        "content document and its ready product report"
                    ),
                )
            )
    for index, link in enumerate(report.get("claim_source_links") or []):
        if not isinstance(link, dict):
            continue
        for artifact_id in link.get("artifact_ids") or []:
            artifact = artifact_map.get(str(artifact_id))
            if artifact is None or artifact.get("scope") != "formal":
                issues.append(
                    VerificationIssue(
                        code="report_claim_artifact_invalid",
                        identity=f"report.claim_source_links[{index}]",
                        message="report claims may reference only sealed formal artifacts",
                    )
                )


def _verify_aox_operation_dag(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    eligible_positive = (
        payload.get("attempt_kind") == "positive"
        and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
        is True
    )
    if not eligible_positive:
        return
    scientific_checks = dict(payload.get("scientific_checks") or {})
    chain = scientific_checks.get("aox_chain")
    if not isinstance(chain, dict):
        issues.append(
            VerificationIssue(
                code="aox_operation_dag_missing",
                identity="scientific_checks.aox_chain",
                message="eligible AOX evidence requires the versioned operation DAG",
            )
        )
        return
    operation_roles = chain.get("operation_roles")
    artifact_roles = chain.get("artifact_roles")
    literature_provider_record_id = str(
        chain.get("literature_provider_record_id") or ""
    )
    scientific_branch = _derive_aox_scientific_branch(
        payload,
        artifact_root=artifact_root,
    )
    required_operation_roles = {
        "ncbi_fetch",
        "hmm_reference_set_selection",
        "scoring_reference_selection",
        "scoring_input_assembly",
        "reference_alignment",
        "hmm_build",
        "hmmer_search",
        "pre_uniprot_score_filter",
        "motif_score",
        "candidate_filter",
        "similarity",
    }
    if scientific_branch == "hmmer_upstream_empty":
        required_operation_roles.update(
            {
                "upstream_empty_materialization",
                "empty_target_scoring_materialization",
                "empty_membership",
            }
        )
    elif scientific_branch == "length_filter_empty":
        required_operation_roles.update(
            {
                "uniprot_fetch",
                "post_uniprot_filter",
                "empty_target_scoring_materialization",
                "empty_membership",
            }
        )
    elif scientific_branch == "motif_filter_empty":
        required_operation_roles.update(
            {
                "uniprot_fetch",
                "post_uniprot_filter",
                "candidate_alignment",
                "empty_membership",
            }
        )
    elif scientific_branch == "nonempty":
        required_operation_roles.update(
            {
                "uniprot_fetch",
                "post_uniprot_filter",
                "candidate_alignment",
                "cdhit",
            }
        )
    required_artifact_roles = {
        "literature_evidence",
        "ncbi_provider_sequences",
        "hmm_reference_set",
        "scoring_reference",
        "scoring_input",
        "reference_alignment",
        "hmm_model",
        "hmmer_response",
        "hmmer_parsed_hits",
        "hmmer_score_filtered_accessions",
        "post_uniprot_filtered_hits",
        "target_sequences",
        "scoring_alignment",
        "motif_scores",
        "candidates",
        "cdhit_membership",
        "graph_nodes",
        "graph_edges",
        "graph_manifest",
    }
    if scientific_branch in {
        "length_filter_empty",
        "motif_filter_empty",
        "nonempty",
    }:
        required_artifact_roles.update(
            {
                "uniprot_sequences",
                "uniprot_metadata",
                "uniprot_raw_response",
            }
        )
    if (
        scientific_branch is None
        or not isinstance(operation_roles, dict)
        or set(operation_roles) != required_operation_roles
        or not isinstance(artifact_roles, dict)
        or set(artifact_roles) != required_artifact_roles
        or not literature_provider_record_id
    ):
        issues.append(
            VerificationIssue(
                code="aox_operation_dag_schema_invalid",
                identity="scientific_checks.aox_chain",
                message="AOX operation and artifact roles do not match the required DAG",
            )
        )
        return
    operations = {
        str(item.get("operation_id") or ""): dict(item)
        for item in payload.get("operations") or []
        if isinstance(item, dict)
    }
    providers = {
        str(item.get("provider_record_id") or ""): dict(item)
        for item in payload.get("provider_identities") or []
        if isinstance(item, dict)
    }
    literature_provider = providers.get(literature_provider_record_id)
    role_operations = {
        role: operations.get(str(operation_id or ""))
        for role, operation_id in operation_roles.items()
    }
    role_artifacts = {
        role: artifact_map.get(str(artifact_id or ""))
        for role, artifact_id in artifact_roles.items()
    }
    if (
        literature_provider is None
        or literature_provider.get("provider") != "pubmed"
        or literature_provider.get("status") != "completed"
        or str(artifact_roles["literature_evidence"])
        not in {str(item) for item in literature_provider.get("artifact_ids") or []}
        or any(operation is None for operation in role_operations.values())
        or any(artifact is None for artifact in role_artifacts.values())
    ):
        issues.append(
            VerificationIssue(
                code="aox_operation_dag_identity_missing",
                identity="scientific_checks.aox_chain",
                message="AOX DAG operation or artifact identity does not resolve",
            )
        )
        return
    if any(
        operation.get("status") != "completed" or operation.get("terminal") is not True
        for operation in role_operations.values()
    ):
        issues.append(
            VerificationIssue(
                code="aox_required_operation_not_completed",
                identity="scientific_checks.aox_chain.operation_roles",
                message="every required positive AOX operation must complete successfully",
            )
        )
    hmm_reference_selection = role_operations["hmm_reference_set_selection"]
    scoring_reference_selection = role_operations["scoring_reference_selection"]
    scoring_input_assembly = role_operations["scoring_input_assembly"]
    ncbi_provider_sequences_artifact = role_artifacts["ncbi_provider_sequences"]
    hmm_reference_set_artifact = role_artifacts["hmm_reference_set"]
    scoring_reference_artifact = role_artifacts["scoring_reference"]
    scoring_input_artifact = role_artifacts["scoring_input"]
    target_sequences_artifact = role_artifacts["target_sequences"]
    assert hmm_reference_selection is not None
    assert scoring_reference_selection is not None
    assert scoring_input_assembly is not None
    assert ncbi_provider_sequences_artifact is not None
    assert hmm_reference_set_artifact is not None
    assert scoring_reference_artifact is not None
    assert scoring_input_artifact is not None
    assert target_sequences_artifact is not None
    reference_chain_valid = False
    try:
        from openzyme_pipeline import aox_reference

        ncbi_provider_sequences_bytes = _resolve_artifact_path(
            artifact_root,
            str(ncbi_provider_sequences_artifact.get("relative_path") or ""),
        ).read_bytes()
        hmm_reference_set_bytes = _resolve_artifact_path(
            artifact_root,
            str(hmm_reference_set_artifact.get("relative_path") or ""),
        ).read_bytes()
        scoring_reference_bytes = _resolve_artifact_path(
            artifact_root,
            str(scoring_reference_artifact.get("relative_path") or ""),
        ).read_bytes()
        scoring_input_bytes = _resolve_artifact_path(
            artifact_root,
            str(scoring_input_artifact.get("relative_path") or ""),
        ).read_bytes()
        target_sequences_bytes = _resolve_artifact_path(
            artifact_root,
            str(target_sequences_artifact.get("relative_path") or ""),
        ).read_bytes()
        hmm_result = aox_reference.select_hmm_reference_set(
            ncbi_provider_sequences_bytes,
            expected_contract_id=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
            ),
            expected_contract_digest=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
            ),
            expected_implementation_digest=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            ),
            expected_input_digest=str(
                ncbi_provider_sequences_artifact.get("content_digest") or ""
            ),
        )
        scoring_reference_result = aox_reference.select_scoring_reference(
            ncbi_provider_sequences_bytes,
            expected_contract_id=(
                aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
            ),
            expected_contract_digest=(
                aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
            ),
            expected_implementation_digest=(
                aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
            ),
            expected_input_digest=str(
                ncbi_provider_sequences_artifact.get("content_digest") or ""
            ),
        )
        scoring_input_result = aox_reference.assemble_scoring_input(
            scoring_reference_bytes,
            target_sequences_bytes,
            expected_contract_id=(aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID),
            expected_contract_digest=(
                aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
            ),
            expected_implementation_digest=(
                aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
            ),
            expected_scoring_reference_input_digest=str(
                scoring_reference_artifact.get("content_digest") or ""
            ),
            expected_target_input_digest=str(
                target_sequences_artifact.get("content_digest") or ""
            ),
        )
        hmm_identity = dict(
            hmm_reference_selection.get("operation_identity_material") or {}
        )
        scoring_reference_identity = dict(
            scoring_reference_selection.get("operation_identity_material") or {}
        )
        scoring_input_identity = dict(
            scoring_input_assembly.get("operation_identity_material") or {}
        )
        reference_chain_valid = (
            hmm_reference_set_bytes == hmm_result.to_fasta().encode("utf-8")
            and scoring_reference_bytes
            == scoring_reference_result.to_fasta().encode("utf-8")
            and scoring_input_bytes == scoring_input_result.to_fasta().encode("utf-8")
            and hmm_reference_set_artifact.get("content_digest")
            == hmm_result.output_digest
            and scoring_reference_artifact.get("content_digest")
            == scoring_reference_result.output_digest
            and scoring_input_artifact.get("content_digest")
            == scoring_input_result.output_digest
            and hmm_identity.get("calculation_id")
            == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
            and hmm_identity.get("calculation_contract_digest")
            == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
            and hmm_identity.get("calculation_implementation_digest")
            == aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            and scoring_reference_identity.get("calculation_id")
            == aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
            and scoring_reference_identity.get("calculation_contract_digest")
            == aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
            and scoring_reference_identity.get("calculation_implementation_digest")
            == aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
            and scoring_input_identity.get("calculation_id")
            == aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
            and scoring_input_identity.get("calculation_contract_digest")
            == aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
            and scoring_input_identity.get("calculation_implementation_digest")
            == aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
            and dict(hmm_reference_selection.get("parameters") or {})
            == {
                "identity_replacement": False,
                "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
            }
            and dict(scoring_reference_selection.get("parameters") or {})
            == {
                "identity_replacement": False,
                "reference_accession": (aox_reference.SCORING_REFERENCE_ACCESSION),
            }
            and dict(scoring_input_assembly.get("parameters") or {})
            == {
                "reference_accession": (aox_reference.SCORING_REFERENCE_ACCESSION),
                "target_count": len(scoring_input_result.targets),
            }
        )
    except (CutoverEvidenceError, OSError, TypeError, ValueError):
        reference_chain_valid = False
    if not reference_chain_valid:
        issues.append(
            VerificationIssue(
                code="aox_reference_chain_invalid",
                identity="scientific_checks.aox_chain.reference_chain",
                message=(
                    "the exact sealed 14-record NCBI response must deterministically "
                    "derive the 13-record HMM set, AAB coordinate reference, and "
                    "AAB-plus-target scoring input under their versioned contracts"
                ),
            )
        )
    if any(
        artifact.get("scope") != "formal"
        or (
            role == "literature_evidence"
            and artifact.get("origin") != "engine_invocation"
        )
        or (role != "literature_evidence" and artifact.get("origin") != "operation")
        for role, artifact in role_artifacts.items()
    ):
        issues.append(
            VerificationIssue(
                code="aox_operation_dag_artifact_invalid",
                identity="scientific_checks.aox_chain.artifact_roles",
                message="AOX DAG artifacts must be formal operation outputs",
            )
        )

    provider_dependencies = chain.get("provider_dependencies")
    dependency_valid = (
        scientific_branch == "hmmer_upstream_empty"
        and _hmmer_upstream_empty_is_proven(payload, artifact_root=artifact_root)
    )
    if (
        scientific_branch != "hmmer_upstream_empty"
        and isinstance(provider_dependencies, list)
        and len(provider_dependencies) == 1
    ):
        dependency = provider_dependencies[0]
        if isinstance(dependency, dict):
            from openzyme_pipeline import aox_hmmer

            upstream = providers.get(
                str(dependency.get("upstream_provider_record_id") or "")
            )
            downstream = providers.get(
                str(dependency.get("downstream_provider_record_id") or "")
            )
            upstream_artifact_ids = [
                str(item)
                for item in dependency.get("upstream_response_artifact_ids") or []
            ]
            derived_accessions = [
                str(item).strip().upper()
                for item in dependency.get("derived_accessions") or []
            ]
            derivation_operation = role_operations.get("pre_uniprot_score_filter")
            parsed_artifact_id = str(dependency.get("parsed_hit_artifact_id") or "")
            parsed_artifact = artifact_map.get(parsed_artifact_id)
            derived_artifact_id = str(
                dependency.get("derived_accession_artifact_id") or ""
            )
            derived_artifact = artifact_map.get(derived_artifact_id)
            uniprot_operation = role_operations.get("uniprot_fetch")
            parameters = (
                dict(uniprot_operation.get("parameters") or {})
                if uniprot_operation is not None
                else {}
            )
            source_hit_artifact = dict(parameters.get("source_hit_artifact") or {})
            recomputed_accessions: list[str] = []
            recomputed_output_digest = ""
            raw_response_body_digests: set[str] = set()
            try:
                if parsed_artifact is None or derived_artifact is None:
                    raise ValueError("missing HMMER derivation artifacts")
                parsed_bytes = _resolve_artifact_path(
                    artifact_root,
                    str(parsed_artifact.get("relative_path") or ""),
                ).read_bytes()
                derived_bytes = _resolve_artifact_path(
                    artifact_root,
                    str(derived_artifact.get("relative_path") or ""),
                ).read_bytes()
                derivation_result = aox_hmmer.parse_and_filter_csv(
                    parsed_bytes,
                    expected_contract_id=aox_hmmer.CONTRACT_ID,
                    expected_contract_digest=aox_hmmer.CONTRACT_DIGEST,
                    expected_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
                )
                expected_bytes = derivation_result.to_csv().encode("utf-8")
                if derived_bytes != expected_bytes:
                    raise ValueError("derived output bytes differ")
                for artifact_id in upstream_artifact_ids:
                    upstream_artifact = artifact_map.get(artifact_id)
                    if upstream_artifact is None:
                        raise ValueError("missing HMMER raw response artifact")
                    raw_envelope = _strict_json_loads(
                        _resolve_artifact_path(
                            artifact_root,
                            str(upstream_artifact.get("relative_path") or ""),
                        ).read_text(encoding="utf-8")
                    )
                    if (
                        not isinstance(raw_envelope, dict)
                        or raw_envelope.get("schema_id")
                        != "provider_raw_http_response_set@1"
                        or raw_envelope.get("provider") != "ebi_hmmer"
                    ):
                        raise ValueError("invalid HMMER raw response envelope")
                    for response in raw_envelope.get("responses") or []:
                        if not isinstance(response, dict):
                            raise ValueError("invalid HMMER raw response record")
                        body = base64.b64decode(
                            str(response.get("body_base64") or ""),
                            validate=True,
                        )
                        body_digest = _sha256(body)
                        if (
                            response.get("body_encoding") != "base64"
                            or response.get("body_digest") != body_digest
                            or response.get("size_bytes") != len(body)
                        ):
                            raise ValueError("invalid HMMER raw response body")
                        raw_response_body_digests.add(body_digest)
                if any(
                    hit.raw_page_digest not in raw_response_body_digests
                    for hit in derivation_result.hits
                ):
                    raise ValueError(
                        "parsed HMMER row is not bound to a raw response page"
                    )
                recomputed_accessions = list(derivation_result.accessions)
                recomputed_output_digest = _sha256(expected_bytes)
            except (
                CutoverEvidenceError,
                OSError,
                UnicodeDecodeError,
                ValueError,
            ):
                recomputed_accessions = []
                recomputed_output_digest = ""
                raw_response_body_digests = set()
            upstream_provider_artifact_ids = {
                str(item) for item in (upstream or {}).get("artifact_ids") or []
            }
            derivation_identity = dict(
                (derivation_operation or {}).get("operation_identity_material") or {}
            )
            dependency_valid = (
                dependency.get("derivation_id") == aox_hmmer.CONTRACT_ID
                and dependency.get("derivation_contract_digest")
                == aox_hmmer.CONTRACT_DIGEST
                and dependency.get("derivation_implementation_digest")
                == aox_hmmer.IMPLEMENTATION_DIGEST
                and upstream is not None
                and upstream.get("provider") == "ebi_hmmer"
                and downstream is not None
                and downstream.get("provider") == "uniprot"
                and downstream.get("operation_id")
                == operation_roles.get("uniprot_fetch")
                and bool(upstream_artifact_ids)
                and len(upstream_artifact_ids) == len(set(upstream_artifact_ids))
                and set(upstream_artifact_ids).issubset(upstream_provider_artifact_ids)
                and all(item in artifact_map for item in upstream_artifact_ids)
                and bool(raw_response_body_digests)
                and parsed_artifact_id
                == str(artifact_roles.get("hmmer_parsed_hits") or "")
                and parsed_artifact_id in upstream_provider_artifact_ids
                and dependency.get("parsed_hit_artifact_digest")
                == (parsed_artifact or {}).get("content_digest")
                and derivation_operation is not None
                and dependency.get("derivation_operation_id")
                == derivation_operation.get("operation_id")
                and derivation_operation.get("canonical_ref_kind")
                == "sandbox_calculation"
                and derivation_identity.get("calculation_id") == aox_hmmer.CONTRACT_ID
                and derivation_identity.get("calculation_contract_digest")
                == aox_hmmer.CONTRACT_DIGEST
                and derivation_identity.get("calculation_implementation_digest")
                == aox_hmmer.IMPLEMENTATION_DIGEST
                and any(
                    isinstance(ref, dict)
                    and ref.get("artifact_id") == parsed_artifact_id
                    and ref.get("content_digest")
                    == (parsed_artifact or {}).get("content_digest")
                    for ref in derivation_operation.get("inputs") or []
                )
                and derived_artifact_id
                == str(artifact_roles.get("hmmer_score_filtered_accessions") or "")
                and derived_artifact is not None
                and dependency.get("derived_accession_artifact_digest")
                == derived_artifact.get("content_digest")
                and recomputed_output_digest == derived_artifact.get("content_digest")
                and any(
                    isinstance(ref, dict)
                    and ref.get("artifact_id") == derived_artifact_id
                    and ref.get("content_digest")
                    == derived_artifact.get("content_digest")
                    for ref in derivation_operation.get("outputs") or []
                )
                and bool(derived_accessions)
                and len(derived_accessions) == len(set(derived_accessions))
                and dependency.get("derived_accessions_digest")
                == canonical_digest(sorted(derived_accessions))
                and derived_accessions == recomputed_accessions
                and sorted(
                    str(item).strip().upper()
                    for item in parameters.get("accessions") or []
                )
                == sorted(derived_accessions)
                and source_hit_artifact.get("artifact_id") == derived_artifact_id
                and source_hit_artifact.get("content_digest")
                == derived_artifact.get("content_digest")
                and source_hit_artifact.get("artifact_id")
                != str(artifact_roles.get("post_uniprot_filtered_hits") or "")
            )
    if not dependency_valid:
        issues.append(
            VerificationIssue(
                code="aox_provider_dependency_invalid",
                identity="scientific_checks.aox_chain.provider_dependencies",
                message=(
                    "HMMER-to-UniProt accession derivation must be recomputable and "
                    "bound to the real downstream operation parameters"
                ),
            )
        )

    def has_ref(operation_role: str, direction: str, artifact_role: str) -> bool:
        operation = role_operations[operation_role]
        artifact = role_artifacts[artifact_role]
        assert operation is not None and artifact is not None
        artifact_id = str(artifact_roles[artifact_role])
        return any(
            isinstance(ref, dict)
            and ref.get("artifact_id") == artifact_id
            and ref.get("content_digest") == artifact.get("content_digest")
            for ref in operation.get(direction) or []
        )

    declared_empty_branch = chain.get("empty_branch")
    empty_branch_valid = False
    if scientific_branch == "nonempty":
        empty_branch_valid = declared_empty_branch is None
    elif scientific_branch == "hmmer_upstream_empty":
        empty_branch_valid = _hmmer_upstream_empty_is_proven(
            payload,
            artifact_root=artifact_root,
        )
    elif scientific_branch in {"length_filter_empty", "motif_filter_empty"}:
        empty_branch = (
            dict(declared_empty_branch)
            if isinstance(declared_empty_branch, dict)
            else {}
        )
        target_artifact = role_artifacts["target_sequences"]
        candidate_artifact = role_artifacts["candidates"]
        assert target_artifact is not None and candidate_artifact is not None
        expected_stage = (
            "sequence_length_join"
            if scientific_branch == "length_filter_empty"
            else "motif_candidate_filter"
        )
        expected_reason = (
            "no_candidates_after_length_filter"
            if scientific_branch == "length_filter_empty"
            else "no_candidates_after_motif_filter"
        )
        trigger_role = (
            "target_sequences"
            if scientific_branch == "length_filter_empty"
            else "candidates"
        )
        trigger_artifact = role_artifacts[trigger_role]
        assert trigger_artifact is not None
        expected_derivation_role = (
            "post_uniprot_filter"
            if scientific_branch == "length_filter_empty"
            else "candidate_filter"
        )
        expected_materialization_id = (
            operation_roles.get("empty_target_scoring_materialization")
            if scientific_branch == "length_filter_empty"
            else None
        )
        expected_omitted_roles = (
            ["candidate_alignment", "cdhit"]
            if scientific_branch == "length_filter_empty"
            else ["cdhit"]
        )
        sequence_join = dict(scientific_checks.get("sequence_join") or {})
        join_counts = dict(
            dict(sequence_join.get("metadata") or {}).get("counts") or {}
        )
        try:
            from openzyme_pipeline import aox_similarity

            target_bytes = _resolve_artifact_path(
                artifact_root,
                str(target_artifact.get("relative_path") or ""),
            ).read_bytes()
            target_count = len(
                aox_similarity.parse_candidate_fasta(target_bytes).records
            )
            candidate_bytes = _resolve_artifact_path(
                artifact_root,
                str(candidate_artifact.get("relative_path") or ""),
            ).read_bytes()
            candidate_count = len(
                aox_similarity.parse_candidate_fasta(candidate_bytes).records
            )
            reference_only_valid = True
            if scientific_branch == "length_filter_empty":
                reference_artifact = role_artifacts["scoring_reference"]
                scoring_artifact = role_artifacts["scoring_alignment"]
                assert reference_artifact is not None and scoring_artifact is not None
                reference_only_valid = (
                    _resolve_artifact_path(
                        artifact_root,
                        str(reference_artifact.get("relative_path") or ""),
                    ).read_bytes()
                    == _resolve_artifact_path(
                        artifact_root,
                        str(scoring_artifact.get("relative_path") or ""),
                    ).read_bytes()
                )
        except (CutoverEvidenceError, OSError, TypeError, ValueError):
            target_count = -1
            candidate_count = -1
            reference_only_valid = False
        membership_operation = role_operations.get("empty_membership")
        membership_identity = dict(
            (membership_operation or {}).get("operation_identity_material") or {}
        )
        materialization_operation = role_operations.get(
            "empty_target_scoring_materialization"
        )
        materialization_identity = dict(
            (materialization_operation or {}).get("operation_identity_material") or {}
        )
        expected_before = (
            join_counts.get("input_hit_count")
            if scientific_branch == "length_filter_empty"
            else target_count
        )
        empty_branch_valid = (
            set(empty_branch)
            == {
                "schema_id",
                "stage",
                "reason",
                "trigger_artifact_id",
                "trigger_artifact_digest",
                "observed_count_before",
                "observed_count_after",
                "derivation_operation_id",
                "skip_provider_record_id",
                "omitted_controlled_roles",
                "empty_materialization_operation_id",
                "empty_membership_operation_id",
            }
            and empty_branch.get("schema_id") == "aox_empty_branch@1"
            and empty_branch.get("stage") == expected_stage
            and empty_branch.get("reason") == expected_reason
            and empty_branch.get("trigger_artifact_id")
            == artifact_roles.get(trigger_role)
            and empty_branch.get("trigger_artifact_digest")
            == trigger_artifact.get("content_digest")
            and empty_branch.get("observed_count_before") == expected_before
            and empty_branch.get("observed_count_after") == 0
            and empty_branch.get("derivation_operation_id")
            == operation_roles.get(expected_derivation_role)
            and empty_branch.get("skip_provider_record_id") is None
            and empty_branch.get("omitted_controlled_roles") == expected_omitted_roles
            and empty_branch.get("empty_materialization_operation_id")
            == expected_materialization_id
            and empty_branch.get("empty_membership_operation_id")
            == operation_roles.get("empty_membership")
            and candidate_count == 0
            and (
                target_count == 0
                if scientific_branch == "length_filter_empty"
                else target_count > 0
            )
            and membership_identity.get("calculation_id")
            == aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID
            and has_ref("empty_membership", "inputs", "candidates")
            and has_ref("empty_membership", "outputs", "cdhit_membership")
            and reference_only_valid
            and (
                scientific_branch != "length_filter_empty"
                or materialization_identity.get("calculation_id")
                == "aox_reference_only_scoring_alignment@1"
            )
        )
    if not empty_branch_valid:
        issues.append(
            VerificationIssue(
                code="aox_empty_branch_invalid",
                identity="scientific_checks.aox_chain.empty_branch",
                message=(
                    "AOX empty/nonempty branch must be derived from sealed artifacts "
                    "and bind exactly the operations it omits or materializes"
                ),
            )
        )

    required_edges = [
        ("ncbi_fetch", "outputs", "ncbi_provider_sequences"),
        (
            "hmm_reference_set_selection",
            "inputs",
            "ncbi_provider_sequences",
        ),
        (
            "hmm_reference_set_selection",
            "outputs",
            "hmm_reference_set",
        ),
        (
            "scoring_reference_selection",
            "inputs",
            "ncbi_provider_sequences",
        ),
        (
            "scoring_reference_selection",
            "outputs",
            "scoring_reference",
        ),
        ("reference_alignment", "inputs", "hmm_reference_set"),
        ("reference_alignment", "outputs", "reference_alignment"),
        ("hmm_build", "inputs", "reference_alignment"),
        ("hmm_build", "outputs", "hmm_model"),
        ("hmmer_search", "inputs", "hmm_model"),
        ("hmmer_search", "outputs", "hmmer_response"),
        ("hmmer_search", "outputs", "hmmer_parsed_hits"),
        ("pre_uniprot_score_filter", "inputs", "hmmer_parsed_hits"),
        (
            "pre_uniprot_score_filter",
            "outputs",
            "hmmer_score_filtered_accessions",
        ),
        ("scoring_input_assembly", "inputs", "scoring_reference"),
        ("scoring_input_assembly", "inputs", "target_sequences"),
        ("scoring_input_assembly", "outputs", "scoring_input"),
        ("motif_score", "inputs", "scoring_alignment"),
        ("motif_score", "outputs", "motif_scores"),
        ("candidate_filter", "inputs", "motif_scores"),
        ("candidate_filter", "inputs", "target_sequences"),
        ("candidate_filter", "outputs", "candidates"),
        ("similarity", "inputs", "candidates"),
        ("similarity", "inputs", "cdhit_membership"),
        ("similarity", "outputs", "graph_nodes"),
        ("similarity", "outputs", "graph_edges"),
        ("similarity", "outputs", "graph_manifest"),
    ]
    if scientific_branch == "hmmer_upstream_empty":
        required_edges.extend(
            [
                (
                    "upstream_empty_materialization",
                    "inputs",
                    "hmmer_score_filtered_accessions",
                ),
                (
                    "upstream_empty_materialization",
                    "outputs",
                    "post_uniprot_filtered_hits",
                ),
                (
                    "upstream_empty_materialization",
                    "outputs",
                    "target_sequences",
                ),
                (
                    "empty_target_scoring_materialization",
                    "inputs",
                    "scoring_input",
                ),
                (
                    "empty_target_scoring_materialization",
                    "inputs",
                    "target_sequences",
                ),
                (
                    "empty_target_scoring_materialization",
                    "outputs",
                    "scoring_alignment",
                ),
                ("empty_membership", "inputs", "candidates"),
                ("empty_membership", "outputs", "cdhit_membership"),
            ]
        )
    else:
        required_edges.extend(
            [
                ("uniprot_fetch", "inputs", "hmmer_score_filtered_accessions"),
                ("uniprot_fetch", "outputs", "uniprot_sequences"),
                ("uniprot_fetch", "outputs", "uniprot_metadata"),
                (
                    "post_uniprot_filter",
                    "inputs",
                    "hmmer_score_filtered_accessions",
                ),
                ("post_uniprot_filter", "inputs", "uniprot_sequences"),
                ("post_uniprot_filter", "inputs", "uniprot_metadata"),
                (
                    "post_uniprot_filter",
                    "outputs",
                    "post_uniprot_filtered_hits",
                ),
                ("post_uniprot_filter", "outputs", "target_sequences"),
            ]
        )
        if scientific_branch == "length_filter_empty":
            required_edges.extend(
                [
                    (
                        "empty_target_scoring_materialization",
                        "inputs",
                        "scoring_input",
                    ),
                    (
                        "empty_target_scoring_materialization",
                        "inputs",
                        "target_sequences",
                    ),
                    (
                        "empty_target_scoring_materialization",
                        "outputs",
                        "scoring_alignment",
                    ),
                    ("empty_membership", "inputs", "candidates"),
                    ("empty_membership", "outputs", "cdhit_membership"),
                ]
            )
        else:
            required_edges.extend(
                [
                    ("candidate_alignment", "inputs", "hmm_model"),
                    ("candidate_alignment", "inputs", "scoring_input"),
                    ("candidate_alignment", "outputs", "scoring_alignment"),
                ]
            )
            if scientific_branch == "motif_filter_empty":
                required_edges.extend(
                    [
                        ("empty_membership", "inputs", "candidates"),
                        ("empty_membership", "outputs", "cdhit_membership"),
                    ]
                )
            else:
                required_edges.extend(
                    [
                        ("cdhit", "inputs", "candidates"),
                        ("cdhit", "outputs", "cdhit_membership"),
                    ]
                )
    missing_edges = [
        f"{operation_role}.{direction}:{artifact_role}"
        for operation_role, direction, artifact_role in required_edges
        if not has_ref(operation_role, direction, artifact_role)
    ]
    if missing_edges:
        issues.append(
            VerificationIssue(
                code="aox_operation_dag_edge_missing",
                identity="scientific_checks.aox_chain",
                message="AOX operation DAG is missing digest-bound edges",
                actual=missing_edges,
            )
        )


def _verify_product_receipts(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    eligible_positive = (
        payload.get("attempt_kind") == "positive"
        and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
        is True
    )
    if not eligible_positive:
        return
    product_path = dict(payload.get("product_path") or {})
    workspace_artifact_id = str(
        product_path.get("workspace_projection_artifact_id") or ""
    )
    event_artifact_id = str(product_path.get("event_log_artifact_id") or "")
    workspace_artifact = artifact_map.get(workspace_artifact_id)
    event_artifact = artifact_map.get(event_artifact_id)
    if workspace_artifact is None or event_artifact is None:
        issues.append(
            VerificationIssue(
                code="product_receipt_artifact_missing",
                identity="product_path",
                message="workspace and event receipts must be sealed formal artifacts",
            )
        )
        return
    try:
        workspace_bytes = _resolve_artifact_path(
            artifact_root,
            str(workspace_artifact.get("relative_path") or ""),
        ).read_bytes()
        event_bytes = _resolve_artifact_path(
            artifact_root,
            str(event_artifact.get("relative_path") or ""),
        ).read_bytes()
        workspace = _strict_json_loads(workspace_bytes.decode("utf-8"))
        events = _strict_json_loads(event_bytes.decode("utf-8"))
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError) as exc:
        issues.append(
            VerificationIssue(
                code="product_receipt_unreadable",
                identity="product_path",
                message=f"product receipt cannot be parsed: {type(exc).__name__}",
            )
        )
        return
    if not isinstance(workspace, dict) or not isinstance(events, dict):
        issues.append(
            VerificationIssue(
                code="product_receipt_schema_invalid",
                identity="product_path",
                message="workspace and event receipts must be JSON objects",
            )
        )
        return
    operations = [
        dict(item) for item in payload.get("operations") or [] if isinstance(item, dict)
    ]
    providers = [
        dict(item)
        for item in payload.get("provider_identities") or []
        if isinstance(item, dict)
    ]
    toolchains = [
        dict(item)
        for item in payload.get("toolchain_identities") or []
        if isinstance(item, dict)
    ]
    approvals = [
        dict(item) for item in payload.get("approvals") or [] if isinstance(item, dict)
    ]
    tasks = [
        dict(item) for item in payload.get("tasks") or [] if isinstance(item, dict)
    ]
    report = dict(payload.get("report") or {})
    final_answer = dict(payload.get("final_answer") or {})
    outcome = dict(payload.get("scientific_outcome") or {})
    launch_receipt = dict(product_path.get("launch_receipt") or {})
    browser_receipt = launch_receipt.get("browser_approval_receipt")
    browser_events = (
        [
            dict(dict(browser_receipt).get("resolution_event_record") or {}),
            dict(dict(browser_receipt).get("continuation_event_record") or {}),
        ]
        if isinstance(browser_receipt, dict)
        else []
    )
    expected_workspace = {
        "schema_id": "aox_workspace_projection_receipt@1",
        "session_id": product_path.get("session_id"),
        "task_ids_by_role": product_path.get("task_ids_by_role"),
        "operation_ids": sorted(
            str(item.get("operation_id") or "") for item in operations
        ),
        "provider_invocation_ids": sorted(
            str(item.get("invocation_id") or "") for item in providers
        ),
        "toolchain_job_ids": sorted(
            str(item.get("job_id") or "") for item in toolchains
        ),
        "report_id": report.get("report_id"),
        "final_master_response_id": product_path.get("final_master_response_id"),
        "root_identity": launch_receipt.get("root_identity"),
        "runtime_config_digest": product_path.get("runtime_config_digest"),
        "cache_hit": product_path.get("cache_hit"),
        "participant_roles": sorted(
            str(item) for item in product_path.get("participant_roles") or []
        ),
        "task_receipts": sorted(
            (
                {
                    "task_id": item.get("task_id"),
                    "role": item.get("role"),
                    "status": item.get("status"),
                    "business_exit": item.get("business_exit"),
                }
                for item in tasks
            ),
            key=lambda item: str(item["task_id"] or ""),
        ),
        "report_receipt": {
            "report_id": report.get("report_id"),
            "session_id": report.get("session_id"),
            "task_id": report.get("task_id"),
            "lane_id": report.get("lane_id"),
            "status": report.get("status"),
            "invocation_id": report.get("invocation_id"),
            "run_id": report.get("run_id"),
            "product_artifact_id": report.get("product_artifact_id"),
            "draft_id": report.get("draft_id"),
            "draft_status": report.get("draft_status"),
            "published_report_id": report.get("published_report_id"),
            "owner_agent_id": report.get("owner_agent_id"),
            "content_ref": report.get("content_ref"),
            "content_document_kind": report.get("content_document_kind"),
            "content_document_invocation_id": report.get(
                "content_document_invocation_id"
            ),
            "content_document_digest": report.get("content_document_digest"),
            "publication_action": report.get("publication_action"),
            "content_artifact_id": report.get("content_artifact_id"),
            "content_digest": report.get("content_digest"),
        },
        "final_answer_receipt": {
            "message_id": final_answer.get("message_id"),
            "content_digest": final_answer.get("content_digest"),
        },
        "scientific_outcome": {
            "status": outcome.get("status"),
            "candidate_count": outcome.get("candidate_count"),
            "empty_result_reason": outcome.get("empty_result_reason"),
            "cutover_eligible": outcome.get("cutover_eligible"),
        },
        "micu_scenario": product_path.get("micu_scenario"),
        "micu_model": product_path.get("micu_model"),
        "micu_invocation_ids": sorted(
            str(item) for item in product_path.get("micu_invocation_ids") or []
        ),
    }
    expected_events = {
        "schema_id": "aox_event_log_receipt@1",
        "session_id": product_path.get("session_id"),
        "entry_message_id": product_path.get("entry_message_id"),
        "entry_message_digest": product_path.get("entry_message_digest"),
        "final_master_response_id": product_path.get("final_master_response_id"),
        "task_ids": sorted(
            str(item)
            for item in dict(product_path.get("task_ids_by_role") or {}).values()
        ),
        "operation_ids": sorted(
            str(item.get("operation_id") or "") for item in operations
        ),
        "approval_bindings": sorted(
            (
                {
                    "approval_id": item.get("approval_id"),
                    "operation_id": item.get("operation_id"),
                    "operation_identity_digest": item.get("operation_identity_digest"),
                }
                for item in approvals
            ),
            key=lambda item: str(item["approval_id"] or ""),
        ),
        "micu_invocation_ids": sorted(
            str(item) for item in product_path.get("micu_invocation_ids") or []
        ),
        "task_finishes": sorted(
            (
                {
                    "task_id": item.get("task_id"),
                    "status": item.get("status"),
                    "business_exit": item.get("business_exit"),
                }
                for item in tasks
            ),
            key=lambda item: str(item["task_id"] or ""),
        ),
        "operation_finishes": sorted(
            (
                {
                    "operation_id": item.get("operation_id"),
                    "operation_identity_digest": item.get("operation_identity_digest"),
                    "status": item.get("status"),
                    "terminal": item.get("terminal"),
                }
                for item in operations
            ),
            key=lambda item: str(item["operation_id"] or ""),
        ),
        "provider_invocations": sorted(
            (
                {
                    "invocation_id": item.get("invocation_id"),
                    "operation_id": item.get("operation_id"),
                    "provider": item.get("provider"),
                    "status": item.get("status"),
                }
                for item in providers
            ),
            key=lambda item: str(item["invocation_id"] or ""),
        ),
        "toolchain_jobs": sorted(
            (
                {
                    "job_id": item.get("job_id"),
                    "operation_id": item.get("operation_id"),
                    "tool": item.get("tool"),
                    "status": item.get("status"),
                }
                for item in toolchains
            ),
            key=lambda item: str(item["job_id"] or ""),
        ),
        "report_publish": {
            "report_id": report.get("report_id"),
            "session_id": report.get("session_id"),
            "task_id": report.get("task_id"),
            "lane_id": report.get("lane_id"),
            "status": report.get("status"),
            "invocation_id": report.get("invocation_id"),
            "run_id": report.get("run_id"),
            "product_artifact_id": report.get("product_artifact_id"),
            "draft_id": report.get("draft_id"),
            "draft_status": report.get("draft_status"),
            "published_report_id": report.get("published_report_id"),
            "owner_agent_id": report.get("owner_agent_id"),
            "content_ref": report.get("content_ref"),
            "content_document_kind": report.get("content_document_kind"),
            "content_document_invocation_id": report.get(
                "content_document_invocation_id"
            ),
            "content_document_digest": report.get("content_document_digest"),
            "publication_action": report.get("publication_action"),
            "content_digest": report.get("content_digest"),
            "publish_events": report.get("publish_events"),
        },
        "browser_approval_events": browser_events,
        "browser_approval_event_stream_digest": canonical_digest(browser_events),
    }
    if (
        workspace != expected_workspace
        or events != expected_events
        or workspace_bytes != canonical_json_bytes(expected_workspace) + b"\n"
        or event_bytes != canonical_json_bytes(expected_events) + b"\n"
        or product_path.get("workspace_projection_digest") != _sha256(workspace_bytes)
        or product_path.get("event_log_digest") != _sha256(event_bytes)
        or product_path.get("browser_approval_event_stream_digest")
        != canonical_digest(browser_events)
        or workspace_artifact.get("scope") != "formal"
        or event_artifact.get("scope") != "formal"
        or workspace_artifact.get("origin") != "attestation"
        or event_artifact.get("origin") != "attestation"
    ):
        issues.append(
            VerificationIssue(
                code="product_receipt_mismatch",
                identity="product_path",
                message="sealed workspace/event receipts differ from product-path identities",
            )
        )


def _provider_canonical_digest(payload: object) -> str:
    return _sha256(
        (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )


def _sequence_join_raw_issue(
    issues: list[VerificationIssue],
    *,
    code: str,
    identity: str,
    message: str,
) -> bool:
    issues.append(
        VerificationIssue(
            code=code,
            identity=identity,
            message=message,
        )
    )
    return False


def _verify_uniprot_raw_sequence_join_closure(
    payload: Mapping[str, Any],
    *,
    check: Mapping[str, Any],
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    metadata_bytes: bytes,
    issues: list[VerificationIssue],
) -> bool:
    raw_artifact_id = check.get("uniprot_raw_response_artifact_id")
    if not isinstance(raw_artifact_id, str) or not raw_artifact_id:
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_artifact_missing",
            identity=(
                "scientific_checks.sequence_join.uniprot_raw_response_artifact_id"
            ),
            message="sequence-join evidence lacks the exact UniProt raw response artifact",
        )
    scientific_checks = dict(payload.get("scientific_checks") or {})
    chain = dict(scientific_checks.get("aox_chain") or {})
    operation_roles = dict(chain.get("operation_roles") or {})
    artifact_roles = dict(chain.get("artifact_roles") or {})
    scientific_artifact_fields = {
        "uniprot_raw_response_artifact_id": "uniprot_raw_response",
        "uniprot_metadata_artifact_id": "uniprot_metadata",
        "uniprot_fasta_artifact_id": "uniprot_sequences",
    }
    scientific_artifacts: dict[str, Mapping[str, Any]] = {}
    scientific_artifact_ids: dict[str, str] = {}
    for field, role in scientific_artifact_fields.items():
        artifact_id = check.get(field)
        artifact = (
            artifact_map.get(artifact_id) if isinstance(artifact_id, str) else None
        )
        if not isinstance(artifact_id, str) or not artifact_id or artifact is None:
            return _sequence_join_raw_issue(
                issues,
                code=(
                    "sequence_join_raw_artifact_missing"
                    if field == "uniprot_raw_response_artifact_id"
                    else "sequence_join_raw_operation_mismatch"
                ),
                identity=f"scientific_checks.sequence_join.{field}",
                message="one required UniProt scientific artifact is absent",
            )
        if artifact_roles.get(role) != artifact_id:
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_operation_mismatch",
                identity=f"scientific_checks.aox_chain.artifact_roles.{role}",
                message=(
                    "sequence-join UniProt artifact does not equal its exact AOX "
                    "scientific artifact role"
                ),
            )
        scientific_artifacts[role] = artifact
        scientific_artifact_ids[role] = artifact_id
    if len(set(scientific_artifact_ids.values())) != len(scientific_artifact_ids):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_operation_mismatch",
            identity="scientific_checks.sequence_join",
            message="UniProt raw, metadata, and FASTA roles must be distinct artifacts",
        )
    raw_artifact = scientific_artifacts["uniprot_raw_response"]

    uniprot_operation_id = operation_roles.get("uniprot_fetch")
    if not isinstance(uniprot_operation_id, str) or not uniprot_operation_id:
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_operation_mismatch",
            identity="scientific_checks.aox_chain.operation_roles.uniprot_fetch",
            message="sequence-join raw evidence lacks its formal UniProt operation",
        )
    operations = [
        item
        for item in payload.get("operations") or []
        if isinstance(item, dict) and item.get("operation_id") == uniprot_operation_id
    ]
    providers = [
        item
        for item in payload.get("provider_identities") or []
        if isinstance(item, dict) and item.get("provider") == "uniprot"
    ]
    if len(operations) != 1 or len(providers) != 1:
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_operation_mismatch",
            identity=f"artifact:{raw_artifact_id}",
            message="UniProt raw evidence does not resolve to one operation/provider closure",
        )
    operation = operations[0]
    provider = providers[0]
    # The online collector excludes provider_request.json and
    # provider_observation.json before it projects formal provider outputs.
    # Consequently every output ref present here is part of the scientific set.
    raw_output_refs = operation.get("outputs")
    output_refs_valid = isinstance(raw_output_refs, list) and all(
        isinstance(ref, dict) for ref in raw_output_refs
    )
    output_refs = list(raw_output_refs) if output_refs_valid else []
    expected_artifact_ids = set(scientific_artifact_ids.values())
    scientific_output_ids = [str(ref.get("artifact_id") or "") for ref in output_refs]
    raw_provider_artifact_ids = provider.get("artifact_ids")
    provider_artifact_ids_valid = isinstance(raw_provider_artifact_ids, list) and all(
        isinstance(artifact_id, str) and artifact_id
        for artifact_id in raw_provider_artifact_ids
    )
    provider_artifact_ids = (
        list(raw_provider_artifact_ids) if provider_artifact_ids_valid else []
    )
    if (
        operation.get("scope") != "formal"
        or operation.get("status") != "completed"
        or provider.get("operation_id") != uniprot_operation_id
        or provider.get("status") != "completed"
        or provider.get("canonical_ref_kind") != "controlled_operation"
        or _DIGEST_PATTERN.fullmatch(str(operation.get("params_digest") or "")) is None
        or provider.get("request_digest") != operation.get("params_digest")
        or not output_refs_valid
        or not provider_artifact_ids_valid
        or len(provider_artifact_ids) != len(expected_artifact_ids)
        or set(provider_artifact_ids) != expected_artifact_ids
        or any(
            provider_artifact_ids.count(artifact_id) != 1
            for artifact_id in expected_artifact_ids
        )
        or len(scientific_output_ids) != len(expected_artifact_ids)
        or set(scientific_output_ids) != expected_artifact_ids
        or any(
            scientific_output_ids.count(artifact_id) != 1
            for artifact_id in expected_artifact_ids
        )
        or any(
            artifact.get("scope") != "formal"
            or artifact.get("origin") != "operation"
            or dict(artifact.get("provenance") or {}).get("operation_id")
            != uniprot_operation_id
            for artifact in scientific_artifacts.values()
        )
        or any(
            next(
                ref for ref in output_refs if ref.get("artifact_id") == artifact_id
            ).get("content_digest")
            != scientific_artifacts[role].get("content_digest")
            for role, artifact_id in scientific_artifact_ids.items()
        )
    ):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_operation_mismatch",
            identity=f"artifact:{raw_artifact_id}",
            message=(
                "UniProt raw response artifact is outside its exact formal "
                "provider-operation output closure"
            ),
        )

    try:
        metadata = _strict_json_loads(metadata_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_metadata_invalid",
            identity="scientific_checks.sequence_join.uniprot_metadata_artifact_id",
            message="UniProt metadata is not strict duplicate-free JSON",
        )
    if not isinstance(metadata, dict):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_metadata_invalid",
            identity="scientific_checks.sequence_join.uniprot_metadata_artifact_id",
            message="UniProt metadata must be a JSON object",
        )
    requested_accessions = metadata.get("requested_accessions")
    active_records = metadata.get("records")
    inactive_records = metadata.get("inactive_records")
    if (
        not isinstance(requested_accessions, list)
        or not requested_accessions
        or not all(
            isinstance(accession, str)
            and accession
            and accession == accession.strip().upper()
            for accession in requested_accessions
        )
        or len(requested_accessions) != len(set(requested_accessions))
        or not isinstance(active_records, list)
        or not all(isinstance(record, dict) for record in active_records)
        or not isinstance(inactive_records, list)
        or not all(isinstance(record, dict) for record in inactive_records)
    ):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_metadata_invalid",
            identity="scientific_checks.sequence_join.uniprot_metadata_artifact_id",
            message="UniProt metadata lacks one closed requested active/inactive partition",
        )
    requested_set = set(requested_accessions)
    operation_parameters = operation.get("parameters")
    operation_accessions = (
        operation_parameters.get("accessions")
        if isinstance(operation_parameters, dict)
        else None
    )
    if operation_accessions != requested_accessions:
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_operation_mismatch",
            identity=f"operation:{uniprot_operation_id}",
            message="UniProt operation accessions differ from the sealed metadata request order",
        )

    try:
        raw_content = _resolve_artifact_path(
            artifact_root,
            str(raw_artifact.get("relative_path") or ""),
        ).read_bytes()
        raw_envelope = _strict_json_loads(raw_content.decode("utf-8"))
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_response_invalid",
            identity=f"artifact:{raw_artifact_id}",
            message="UniProt raw response envelope is not strict duplicate-free JSON",
        )
    if (
        not isinstance(raw_envelope, dict)
        or set(raw_envelope) != {"schema_id", "provider", "operation", "responses"}
        or raw_envelope.get("schema_id") != "provider_raw_http_response_set@1"
        or raw_envelope.get("provider") != "uniprot"
        or raw_envelope.get("operation") != "bio.uniprot_fetch"
        or not isinstance(raw_envelope.get("responses"), list)
        or not raw_envelope["responses"]
    ):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_response_invalid",
            identity=f"artifact:{raw_artifact_id}",
            message="UniProt raw response envelope has the wrong closed schema or identity",
        )

    response_digests: list[str] = []
    release_headers: list[object] = []
    release_date_headers: list[object] = []
    raw_results: list[dict[str, Any]] = []
    response_keys = {
        "ordinal",
        "phase",
        "status_code",
        "headers",
        "body_encoding",
        "body_base64",
        "body_digest",
        "size_bytes",
    }
    for ordinal, response in enumerate(raw_envelope["responses"], start=1):
        if not isinstance(response, dict) or set(response) != response_keys:
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_response_invalid",
                identity=f"artifact:{raw_artifact_id}:response:{ordinal}",
                message="UniProt raw response record has an open or malformed schema",
            )
        encoded = response.get("body_base64")
        try:
            body = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_response_invalid",
                identity=f"artifact:{raw_artifact_id}:response:{ordinal}",
                message="UniProt raw response body is not canonical base64",
            )
        body_digest = _sha256(body)
        status_code = response.get("status_code")
        if (
            response.get("ordinal") != ordinal
            or response.get("phase") != f"page:{ordinal}"
            or isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 200 <= status_code < 300
            or not isinstance(response.get("headers"), dict)
            or response.get("body_encoding") != "base64"
            or encoded != base64.b64encode(body).decode("ascii")
            or response.get("size_bytes") != len(body)
            or response.get("body_digest") != body_digest
        ):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_response_invalid",
                identity=f"artifact:{raw_artifact_id}:response:{ordinal}",
                message="UniProt raw response size, digest, order, or status is inconsistent",
            )
        try:
            body_payload = _strict_json_loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_response_invalid",
                identity=f"artifact:{raw_artifact_id}:response:{ordinal}:body",
                message="UniProt raw response body is not strict duplicate-free JSON",
            )
        if (
            not isinstance(body_payload, dict)
            or not isinstance(body_payload.get("results"), list)
            or not all(isinstance(result, dict) for result in body_payload["results"])
        ):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_response_invalid",
                identity=f"artifact:{raw_artifact_id}:response:{ordinal}:body",
                message="UniProt raw response body lacks a results array of objects",
            )
        response_digests.append(body_digest)
        headers = response["headers"]
        release_headers.append(headers.get("x-uniprot-release"))
        release_date_headers.append(headers.get("x-uniprot-release-date"))
        for result in body_payload["results"]:
            raw_results.append(
                {
                    "result": result,
                    "response_digest": body_digest,
                }
            )

    if (
        not all(
            isinstance(value, str) and value and value == value.strip()
            for value in release_headers
        )
        or len(set(release_headers)) != 1
        or metadata.get("uniprot_release") != release_headers[0]
    ):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_release_mismatch",
            identity="scientific_checks.sequence_join",
            message=(
                "UniProt metadata release does not equal one required value on "
                "every raw response page"
            ),
        )
    present_release_dates = [
        value for value in release_date_headers if isinstance(value, str) and value
    ]
    release_dates_valid = (
        not present_release_dates
        and all(value is None for value in release_date_headers)
        and metadata.get("uniprot_release_date") is None
    ) or (
        len(present_release_dates) == len(release_date_headers)
        and all(value == value.strip() for value in present_release_dates)
        and len(set(present_release_dates)) == 1
        and metadata.get("uniprot_release_date") == present_release_dates[0]
    )
    if not release_dates_valid:
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_release_mismatch",
            identity="scientific_checks.sequence_join",
            message=(
                "optional UniProt release-date header is partial, inconsistent, "
                "or differs from metadata"
            ),
        )

    declared_response_digests = metadata.get("response_digests")
    if (
        declared_response_digests != response_digests
        or metadata.get("aggregate_response_digest")
        != _provider_canonical_digest(response_digests)
        or provider.get("response_digest") != response_digests[-1]
    ):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_response_digest_mismatch",
            identity="scientific_checks.sequence_join",
            message=(
                "UniProt metadata/provider receipt does not reproduce the ordered raw "
                "response digest chain"
            ),
        )

    try:
        from openzyme_engines.execution import _sanitize_provider_value
    except ImportError:
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_record_mismatch",
            identity="scientific_checks.sequence_join",
            message="UniProt provider record sanitizer is unavailable offline",
        )

    reviewed_by_active_entry_type = {
        "UniProtKB reviewed (Swiss-Prot)": True,
        "UniProtKB unreviewed (TrEMBL)": False,
    }
    raw_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_record in raw_results:
        result = dict(raw_record["result"])
        primary_accession = result.get("primaryAccession")
        entry_type = result.get("entryType")
        if (
            not isinstance(primary_accession, str)
            or not primary_accession
            or primary_accession != primary_accession.strip().upper()
            or not isinstance(entry_type, str)
            or not entry_type
        ):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"artifact:{raw_artifact_id}:raw_result",
                message="UniProt raw result lacks canonical primary/discriminator identity",
            )
        inactive = entry_type == "Inactive"
        if inactive:
            if "sequence" in result or "entryAudit" in result:
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                    message="inactive UniProt raw result carries forbidden sequence/audit",
                )
            requested_accession = primary_accession
            if requested_accession not in requested_set:
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                    message="inactive UniProt raw result does not equal one requested primary",
                )
        else:
            expected_reviewed = reviewed_by_active_entry_type.get(entry_type)
            explicit_reviewed = result.get("reviewed")
            if (
                expected_reviewed is None
                or "inactiveReason" in result
                or (
                    explicit_reviewed is not None
                    and (
                        not isinstance(explicit_reviewed, bool)
                        or explicit_reviewed is not expected_reviewed
                    )
                )
            ):
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                    message=(
                        "active UniProt raw result has an unsupported entry type, "
                        "inactive reason, or reviewed discriminator"
                    ),
                )
            secondary_accessions = result.get("secondaryAccessions") or []
            if not isinstance(secondary_accessions, list) or not all(
                isinstance(accession, str) for accession in secondary_accessions
            ):
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                    message="active UniProt raw result has malformed secondary identity",
                )
            normalized_secondary = [
                accession.strip().upper() for accession in secondary_accessions
            ]
            matches = list(
                dict.fromkeys(
                    accession
                    for accession in [primary_accession, *normalized_secondary]
                    if accession in requested_set
                )
            )
            if len(matches) != 1:
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                    message="active UniProt raw result does not map to exactly one request",
                )
            requested_accession = matches[0]
        identity = (requested_accession, primary_accession)
        if identity in raw_by_identity:
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                message="UniProt raw results duplicate one requested/primary identity",
            )
        sanitized = _sanitize_provider_value(result)
        if not isinstance(sanitized, dict):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"artifact:{raw_artifact_id}:{primary_accession}",
                message="UniProt raw result cannot be canonically sanitized",
            )
        provider_metadata = dict(sanitized)
        provider_metadata.pop("sequence", None)
        raw_by_identity[identity] = {
            "active": not inactive,
            "entry_type": entry_type,
            "reviewed": (
                None if inactive else reviewed_by_active_entry_type[entry_type]
            ),
            "inactive_reason": result.get("inactiveReason"),
            "sequence": result.get("sequence"),
            "provider_metadata": provider_metadata,
            "record_digest": _provider_canonical_digest(sanitized),
            "response_digest": raw_record["response_digest"],
        }

    metadata_by_identity: dict[tuple[str, str], tuple[dict[str, Any], bool]] = {}
    for active, records in ((True, active_records), (False, inactive_records)):
        for record in records:
            requested_accession = record.get("requested_accession")
            primary_accession = record.get("primary_accession")
            if (
                not isinstance(requested_accession, str)
                or requested_accession not in requested_set
                or not isinstance(primary_accession, str)
                or not primary_accession
            ):
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity="scientific_checks.sequence_join.uniprot_metadata",
                    message="UniProt metadata record has malformed requested/primary identity",
                )
            identity = (requested_accession, primary_accession)
            if identity in metadata_by_identity:
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"scientific_checks.sequence_join:{primary_accession}",
                    message="UniProt metadata duplicates one requested/primary identity",
                )
            if active:
                metadata_entry_type = record.get("entry_type")
                expected_reviewed = (
                    reviewed_by_active_entry_type.get(metadata_entry_type)
                    if isinstance(metadata_entry_type, str)
                    else None
                )
                discriminator_valid = (
                    expected_reviewed is not None
                    and record.get("reviewed") is expected_reviewed
                    and "inactive_reason" not in record
                )
            else:
                reason = record.get("inactive_reason")
                discriminator_valid = (
                    requested_accession == primary_accession
                    and record.get("entry_type") == "Inactive"
                    and isinstance(reason, dict)
                    and reason.get("inactive_reason_type") in {"DELETED", "MERGED"}
                )
            if not discriminator_valid:
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_record_mismatch",
                    identity=f"scientific_checks.sequence_join:{primary_accession}",
                    message="UniProt metadata active/inactive discriminator is inconsistent",
                )
            metadata_by_identity[identity] = (record, active)

    if (
        set(metadata_by_identity) != set(raw_by_identity)
        or {identity[0] for identity in metadata_by_identity} != requested_set
        or len(metadata_by_identity) != len(requested_accessions)
        or metadata.get("active_record_count") != len(active_records)
        or metadata.get("inactive_record_count") != len(inactive_records)
    ):
        return _sequence_join_raw_issue(
            issues,
            code="sequence_join_raw_record_mismatch",
            identity="scientific_checks.sequence_join",
            message="UniProt raw results and metadata do not form one exact identity partition",
        )

    for identity, (record, active) in metadata_by_identity.items():
        raw_record = raw_by_identity[identity]
        if (
            raw_record["active"] is not active
            or record.get("entry_type") != raw_record["entry_type"]
            or (active and record.get("reviewed") is not raw_record["reviewed"])
            or record.get("record_digest") != raw_record["record_digest"]
            or record.get("response_digest") != raw_record["response_digest"]
            or record.get("provider_metadata") != raw_record["provider_metadata"]
        ):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"scientific_checks.sequence_join:{identity[1]}",
                message="UniProt metadata record does not reproduce its unique raw result",
            )
        if active:
            sequence_payload = raw_record["sequence"]
            sequence_value = (
                sequence_payload.get("value")
                if isinstance(sequence_payload, dict)
                else None
            )
            declared_length = (
                sequence_payload.get("length")
                if isinstance(sequence_payload, dict)
                else None
            )
            sequence = (
                sequence_value.strip().upper()
                if isinstance(sequence_value, str)
                else ""
            )
            if (
                not sequence
                or re.fullmatch(r"[A-Z*.-]+", sequence) is None
                or isinstance(declared_length, bool)
                or not isinstance(declared_length, int)
                or declared_length != len(sequence)
                or record.get("sequence_length") != len(sequence)
                or record.get("sequence_digest") != _sha256(sequence.encode("utf-8"))
            ):
                return _sequence_join_raw_issue(
                    issues,
                    code="sequence_join_raw_sequence_mismatch",
                    identity=f"scientific_checks.sequence_join:{identity[1]}",
                    message=(
                        "active UniProt raw sequence bytes/length differ from the "
                        "metadata identity consumed by the FASTA join"
                    ),
                )
            continue
        raw_reason = raw_record["inactive_reason"]
        metadata_reason = record.get("inactive_reason")
        if not isinstance(raw_reason, dict) or not isinstance(metadata_reason, dict):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"scientific_checks.sequence_join:{identity[1]}",
                message="inactive UniProt reason is missing from raw or metadata evidence",
            )
        reason_type = raw_reason.get("inactiveReasonType")
        if reason_type != metadata_reason.get("inactive_reason_type"):
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"scientific_checks.sequence_join:{identity[1]}",
                message="inactive UniProt reason discriminator differs from the raw result",
            )
        if reason_type == "DELETED":
            reason_valid = metadata_reason == {
                "inactive_reason_type": "DELETED",
                "deleted_reason": raw_reason.get("deletedReason"),
            }
        elif reason_type == "MERGED":
            raw_targets = raw_reason.get("mergeDemergeTo")
            expected_annotations = (
                [
                    {
                        "annotation_type": "provider_inactive_replacement",
                        "source_database": "uniprotkb",
                        "source_accession": identity[0],
                        "target_database": "uniprotkb",
                        "target_accession": target,
                        "relationship": "merged_into",
                        "identity_replaced": False,
                        "target_followed": False,
                    }
                    for target in sorted(raw_targets)
                ]
                if isinstance(raw_targets, list)
                and raw_targets
                and all(isinstance(target, str) for target in raw_targets)
                else None
            )
            reason_valid = metadata_reason == {
                "inactive_reason_type": "MERGED",
                "replacement_target_annotations": expected_annotations,
            }
        else:
            reason_valid = False
        if not reason_valid:
            return _sequence_join_raw_issue(
                issues,
                code="sequence_join_raw_record_mismatch",
                identity=f"scientific_checks.sequence_join:{identity[1]}",
                message=(
                    "inactive UniProt reason or MERGED non-follow annotation differs "
                    "from the raw result"
                ),
            )
    return True


def _verify_sequence_join(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    eligible_positive = (
        payload.get("attempt_kind") == "positive"
        and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
        is True
    )
    if not eligible_positive:
        return
    scientific_checks = dict(payload.get("scientific_checks") or {})
    check = scientific_checks.get("sequence_join")
    if _hmmer_upstream_empty_is_proven(payload, artifact_root=artifact_root):
        if check is not None:
            issues.append(
                VerificationIssue(
                    code="sequence_join_check_forbidden",
                    identity="scientific_checks.sequence_join",
                    message=(
                        "upstream-empty AOX evidence must not claim a UniProt "
                        "sequence join"
                    ),
                )
            )
        return
    if not isinstance(check, dict):
        issues.append(
            VerificationIssue(
                code="sequence_join_check_missing",
                identity="scientific_checks.sequence_join",
                message="eligible AOX evidence requires offline UniProt sequence-join recomputation",
            )
        )
        return
    artifact_fields = {
        "score_filtered_artifact_id": "score_filtered",
        "uniprot_fasta_artifact_id": "uniprot_fasta",
        "uniprot_metadata_artifact_id": "uniprot_metadata",
        "filtered_hits_artifact_id": "filtered_hits",
        "target_fasta_artifact_id": "target_fasta",
    }
    resolved: dict[str, bytes] = {}
    for field, label in artifact_fields.items():
        artifact_id = str(check.get(field) or "")
        artifact = artifact_map.get(artifact_id)
        if artifact is None:
            issues.append(
                VerificationIssue(
                    code="sequence_join_artifact_missing",
                    identity=f"scientific_checks.sequence_join.{field}",
                    message="sequence-join input or output artifact is missing",
                )
            )
            continue
        try:
            resolved[label] = _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_bytes()
        except (CutoverEvidenceError, OSError) as exc:
            issues.append(
                VerificationIssue(
                    code="sequence_join_artifact_unreadable",
                    identity=f"artifact:{artifact_id}",
                    message=f"sequence-join artifact is unreadable: {type(exc).__name__}",
                )
            )
    if len(resolved) != len(artifact_fields):
        return
    if not _verify_uniprot_raw_sequence_join_closure(
        payload,
        check=check,
        artifact_root=artifact_root,
        artifact_map=artifact_map,
        metadata_bytes=resolved["uniprot_metadata"],
        issues=issues,
    ):
        return
    try:
        from openzyme_pipeline import aox_hmmer, aox_sequence_join

        result = aox_sequence_join.join_score_filtered_accessions(
            resolved["score_filtered"],
            resolved["uniprot_fasta"],
            resolved["uniprot_metadata"],
            expected_contract_id=str(check.get("contract_id") or ""),
            expected_contract_digest=str(check.get("contract_digest") or ""),
            expected_implementation_digest=str(
                check.get("implementation_digest") or ""
            ),
            expected_hmmer_contract_id=aox_hmmer.CONTRACT_ID,
            expected_hmmer_contract_digest=aox_hmmer.CONTRACT_DIGEST,
            expected_hmmer_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
            expected_score_filtered_csv_digest=_sha256(resolved["score_filtered"]),
            expected_uniprot_fasta_digest=_sha256(resolved["uniprot_fasta"]),
            expected_uniprot_metadata_digest=_sha256(resolved["uniprot_metadata"]),
        )
        expected_hits = result.hits_csv().encode("utf-8")
        expected_fasta = result.target_fasta().encode("utf-8")
        expected_metadata = result.metadata()
    except Exception as exc:
        issues.append(
            VerificationIssue(
                code="sequence_join_recompute_failed",
                identity="scientific_checks.sequence_join",
                message=f"offline sequence-join recomputation failed: {type(exc).__name__}",
            )
        )
        return
    if (
        resolved["filtered_hits"] != expected_hits
        or resolved["target_fasta"] != expected_fasta
        or check.get("metadata") != expected_metadata
    ):
        issues.append(
            VerificationIssue(
                code="sequence_join_output_mismatch",
                identity="scientific_checks.sequence_join",
                message="post-UniProt hits, target FASTA, or metadata differ from recomputation",
                expected={
                    "filtered_hits_digest": _sha256(expected_hits),
                    "target_fasta_digest": _sha256(expected_fasta),
                },
                actual={
                    "filtered_hits_digest": _sha256(resolved["filtered_hits"]),
                    "target_fasta_digest": _sha256(resolved["target_fasta"]),
                },
            )
        )


def _verify_scoring(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    scientific_checks = dict(payload.get("scientific_checks") or {})
    scoring = scientific_checks.get("scoring")
    if scoring is None:
        if (
            payload.get("attempt_kind") == "positive"
            and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
            is True
        ):
            issues.append(
                VerificationIssue(
                    code="scoring_check_missing",
                    identity="scientific_checks.scoring",
                    message="positive AOX attempt requires offline scoring recomputation",
                )
            )
        return
    if not isinstance(scoring, dict):
        issues.append(
            VerificationIssue(
                code="scoring_check_invalid",
                identity="scientific_checks.scoring",
                message="scoring check must be an object",
            )
        )
        return
    alignment_id = str(scoring.get("alignment_artifact_id") or "")
    scored_id = str(scoring.get("scored_artifact_id") or "")
    alignment = artifact_map.get(alignment_id)
    scored = artifact_map.get(scored_id)
    if alignment is None or scored is None:
        issues.append(
            VerificationIssue(
                code="scoring_artifact_missing",
                identity="scientific_checks.scoring",
                message="alignment or scored artifact is missing",
            )
        )
        return
    try:
        from openzyme_pipeline import aox_motif

        alignment_bytes = _resolve_artifact_path(
            artifact_root, str(alignment["relative_path"])
        ).read_bytes()
        scored_bytes = _resolve_artifact_path(
            artifact_root, str(scored["relative_path"])
        ).read_bytes()
        result = aox_motif.score_aligned_fasta(
            alignment_bytes,
            expected_contract_id=str(scoring.get("scoring_contract_id") or ""),
            expected_contract_digest=str(scoring.get("scoring_contract_digest") or ""),
            expected_implementation_digest=str(
                scoring.get("scoring_implementation_digest") or ""
            ),
            expected_input_digest=str(scoring.get("input_digest") or ""),
        )
        expected_csv = result.to_csv().encode("utf-8")
    except Exception as exc:
        issues.append(
            VerificationIssue(
                code="scoring_recompute_failed",
                identity="scientific_checks.scoring",
                message=f"offline scoring recomputation failed: {type(exc).__name__}",
            )
        )
        return
    if scored_bytes != expected_csv:
        issues.append(
            VerificationIssue(
                code="scoring_output_mismatch",
                identity=f"artifact:{scored_id}",
                message="canonical scored CSV does not match recomputed alignment scores",
                expected=_sha256(expected_csv),
                actual=_sha256(scored_bytes),
            )
        )


_SIMILARITY_ARTIFACT_FIELDS = (
    ("candidate_fasta_artifact_id", "candidate_fasta"),
    ("membership_artifact_id", "membership_csv"),
    ("nodes_artifact_id", "nodes_csv"),
    ("edges_artifact_id", "edges_csv"),
    ("manifest_artifact_id", "manifest_json"),
)


def _similarity_validation_parameters(
    similarity: Mapping[str, Any],
) -> _SimilarityValidationParameters:
    return _SimilarityValidationParameters(
        threshold_ppm=int(similarity.get("threshold_ppm")),
        empty_result_reason=(
            None
            if similarity.get("empty_result_reason") is None
            else str(similarity.get("empty_result_reason"))
        ),
        calculation_id=str(similarity.get("calculation_id") or ""),
        calculation_digest=str(similarity.get("calculation_digest") or ""),
        implementation_digest=str(similarity.get("implementation_digest") or ""),
        candidate_fasta_digest=str(similarity.get("candidate_fasta_digest") or ""),
        membership_digest=str(similarity.get("membership_digest") or ""),
    )


def _similarity_artifact_bindings(
    similarity: Mapping[str, Any],
    resolved: Mapping[str, bytes],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            field,
            str(similarity.get(field) or ""),
            _sha256(resolved[label]),
        )
        for field, label in _SIMILARITY_ARTIFACT_FIELDS
    )


def _validate_similarity_graph(
    resolved: Mapping[str, bytes],
    *,
    parameters: _SimilarityValidationParameters,
) -> Any:
    from openzyme_pipeline import aox_similarity

    return aox_similarity.validate_graph_artifacts(
        resolved["candidate_fasta"],
        resolved["membership_csv"],
        resolved["nodes_csv"],
        resolved["edges_csv"],
        resolved["manifest_json"],
        threshold_ppm=parameters.threshold_ppm,
        empty_result_reason=parameters.empty_result_reason,
        expected_calculation_id=parameters.calculation_id,
        expected_calculation_digest=parameters.calculation_digest,
        expected_implementation_digest=parameters.implementation_digest,
        expected_candidate_fasta_digest=parameters.candidate_fasta_digest,
        expected_membership_digest=parameters.membership_digest,
    )


def _verify_similarity(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> _VerifiedSimilarityGraph | None:
    scientific_checks = dict(payload.get("scientific_checks") or {})
    similarity = scientific_checks.get("similarity")
    eligible_positive = (
        payload.get("attempt_kind") == "positive"
        and dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
        is True
    )
    if similarity is None:
        if eligible_positive:
            issues.append(
                VerificationIssue(
                    code="similarity_check_missing",
                    identity="scientific_checks.similarity",
                    message="eligible AOX attempt requires offline graph recomputation",
                )
            )
        return
    if not isinstance(similarity, dict):
        issues.append(
            VerificationIssue(
                code="similarity_check_invalid",
                identity="scientific_checks.similarity",
                message="similarity check must be an object",
            )
        )
        return
    resolved: dict[str, bytes] = {}
    for field, label in _SIMILARITY_ARTIFACT_FIELDS:
        artifact_id = str(similarity.get(field) or "")
        artifact = artifact_map.get(artifact_id)
        if artifact is None:
            issues.append(
                VerificationIssue(
                    code="similarity_artifact_missing",
                    identity=f"scientific_checks.similarity.{field}",
                    message="similarity graph input or output artifact is missing",
                )
            )
            continue
        try:
            resolved[label] = _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_bytes()
        except (CutoverEvidenceError, OSError) as exc:
            issues.append(
                VerificationIssue(
                    code="similarity_artifact_unreadable",
                    identity=f"artifact:{artifact_id}",
                    message=f"similarity artifact bytes are unavailable: {type(exc).__name__}",
                )
            )
    if len(resolved) != len(_SIMILARITY_ARTIFACT_FIELDS):
        return
    try:
        parameters = _similarity_validation_parameters(similarity)
        graph_result = _validate_similarity_graph(
            resolved,
            parameters=parameters,
        )
    except Exception as exc:
        details = getattr(exc, "details", {})
        issues.append(
            VerificationIssue(
                code="similarity_recompute_failed",
                identity="scientific_checks.similarity",
                message=(
                    f"offline similarity graph recomputation failed: {type(exc).__name__}"
                    + (
                        ""
                        if not isinstance(details, dict) or not details.get("field")
                        else f" ({details['field']})"
                    )
                ),
            )
        )
        return None
    return _VerifiedSimilarityGraph(
        artifact_bindings=_similarity_artifact_bindings(similarity, resolved),
        parameters=parameters,
        graph_result=graph_result,
    )


def _verify_scientific_outcome(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
    verified_similarity: _VerifiedSimilarityGraph | None,
) -> None:
    outcome = dict(payload.get("scientific_outcome") or {})
    eligible_positive = (
        payload.get("attempt_kind") == "positive"
        and outcome.get("cutover_eligible") is True
    )
    if not eligible_positive:
        return
    scientific_checks = dict(payload.get("scientific_checks") or {})
    scoring = scientific_checks.get("scoring")
    similarity = scientific_checks.get("similarity")
    chain = scientific_checks.get("aox_chain")
    if not all(isinstance(item, dict) for item in (scoring, similarity, chain)):
        issues.append(
            VerificationIssue(
                code="scientific_outcome_binding_missing",
                identity="scientific_outcome",
                message="eligible outcome requires scoring, similarity, and AOX DAG checks",
            )
        )
        return
    assert isinstance(scoring, dict)
    assert isinstance(similarity, dict)
    assert isinstance(chain, dict)
    artifact_fields = {
        "alignment": str(scoring.get("alignment_artifact_id") or ""),
        "candidates": str(similarity.get("candidate_fasta_artifact_id") or ""),
        "membership": str(similarity.get("membership_artifact_id") or ""),
        "nodes": str(similarity.get("nodes_artifact_id") or ""),
        "edges": str(similarity.get("edges_artifact_id") or ""),
        "manifest": str(similarity.get("manifest_artifact_id") or ""),
    }
    resolved: dict[str, bytes] = {}
    for label, artifact_id in artifact_fields.items():
        artifact = artifact_map.get(artifact_id)
        if artifact is None:
            issues.append(
                VerificationIssue(
                    code="scientific_outcome_artifact_missing",
                    identity=f"scientific_outcome.{label}",
                    message="scientific outcome input artifact is missing",
                )
            )
            continue
        try:
            resolved[label] = _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_bytes()
        except (CutoverEvidenceError, OSError) as exc:
            issues.append(
                VerificationIssue(
                    code="scientific_outcome_artifact_unreadable",
                    identity=f"scientific_outcome.{label}",
                    message=f"scientific outcome artifact is unreadable: {type(exc).__name__}",
                )
            )
    if len(resolved) != len(artifact_fields):
        return
    excluded_raw = chain.get("excluded_scoring_sequence_ids")
    if not isinstance(excluded_raw, list) or not all(
        isinstance(item, str) and item for item in excluded_raw
    ):
        issues.append(
            VerificationIssue(
                code="scientific_outcome_exclusion_invalid",
                identity="scientific_checks.aox_chain.excluded_scoring_sequence_ids",
                message="candidate exclusions must be an explicit array of sequence ids",
            )
        )
        return
    try:
        from openzyme_pipeline import aox_motif

        scoring_result = aox_motif.score_aligned_fasta(
            resolved["alignment"],
            expected_contract_id=str(scoring.get("scoring_contract_id") or ""),
            expected_contract_digest=str(scoring.get("scoring_contract_digest") or ""),
            expected_implementation_digest=str(
                scoring.get("scoring_implementation_digest") or ""
            ),
            expected_input_digest=str(scoring.get("input_digest") or ""),
        )
        similarity_resolved = {
            "candidate_fasta": resolved["candidates"],
            "membership_csv": resolved["membership"],
            "nodes_csv": resolved["nodes"],
            "edges_csv": resolved["edges"],
            "manifest_json": resolved["manifest"],
        }
        parameters = _similarity_validation_parameters(similarity)
        artifact_bindings = _similarity_artifact_bindings(
            similarity,
            similarity_resolved,
        )
        if (
            verified_similarity is not None
            and verified_similarity.parameters == parameters
            and verified_similarity.artifact_bindings == artifact_bindings
        ):
            graph_result = verified_similarity.graph_result
        else:
            graph_result = _validate_similarity_graph(
                similarity_resolved,
                parameters=parameters,
            )
    except Exception as exc:
        issues.append(
            VerificationIssue(
                code="scientific_outcome_recompute_failed",
                identity="scientific_outcome",
                message=f"scientific outcome inputs could not be recomputed: {type(exc).__name__}",
            )
        )
        return
    excluded = set(excluded_raw)
    expected_candidates = {
        row.sequence_id: row.sequence_digest
        for row in scoring_result.rows
        if row.passes_motif_rule and row.sequence_id not in excluded
    }
    candidate_sequences = {
        record.sequence_id: record.sequence_digest
        for record in graph_result.sequences.records
    }
    graph_node_ids = {node.sequence.sequence_id for node in graph_result.nodes}
    candidate_count = outcome.get("candidate_count")
    status = outcome.get("status")
    outcome_reason = outcome.get("empty_result_reason")
    similarity_reason = similarity.get("empty_result_reason")
    nonempty = bool(expected_candidates)
    consistent_status = (
        status == "discovered"
        and outcome_reason in {None, ""}
        and similarity_reason is None
        if nonempty
        else status == "empty"
        and isinstance(outcome_reason, str)
        and bool(outcome_reason.strip())
        and outcome_reason == similarity_reason
        and graph_result.empty_result_reason == outcome_reason
    )
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count != len(expected_candidates)
        or candidate_sequences != expected_candidates
        or graph_node_ids != set(expected_candidates)
        or len(graph_result.nodes) != len(expected_candidates)
        or not consistent_status
    ):
        issues.append(
            VerificationIssue(
                code="scientific_outcome_artifact_mismatch",
                identity="scientific_outcome",
                message="declared discovery/empty outcome contradicts recomputed candidates or graph",
                expected={
                    "candidate_count": len(expected_candidates),
                    "status": "discovered" if nonempty else "empty",
                },
                actual={
                    "candidate_count": candidate_count,
                    "status": status,
                    "graph_node_count": len(graph_result.nodes),
                },
            )
        )


def _verify_fault_injection(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    if payload.get("attempt_kind") != "fault":
        return
    fault = dict(payload.get("fault_injection") or {})
    if fault.get("reached_target_seam") is not True:
        return
    target_artifact_id = str(fault.get("target_artifact_id") or "")
    target_artifact = artifact_map.get(target_artifact_id)
    if target_artifact is None:
        issues.append(
            VerificationIssue(
                code="fault_target_artifact_missing",
                identity="fault_injection.target_artifact_id",
                message="controlled fault target does not resolve to a sealed artifact",
            )
        )
        return
    target_contract_path = "aox_hmm/AOX_ref21.fasta"
    target_provenance = dict(target_artifact.get("provenance") or {})
    expected_target_kind, expected_target_format = (
        AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS[target_contract_path]
    )
    if (
        target_artifact.get("deliverable_path") != target_contract_path
        or target_provenance.get("catalog_relative_path") != target_contract_path
        or target_artifact.get("deliverable_artifact_contract_id")
        != AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
        or target_provenance.get("deliverable_artifact_contract_id")
        != AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
        or target_artifact.get("kind") != expected_target_kind
        or target_artifact.get("format") != expected_target_format
    ):
        issues.append(
            VerificationIssue(
                code="fault_target_artifact_contract_mismatch",
                identity=f"artifact:{target_artifact_id}:wire_contract",
                message=(
                    "controlled AOX reference fault target must retain its exact "
                    "sequence/fasta deliverable contract"
                ),
            )
        )
    relative_path = str(fault.get("relative_path") or "")
    if relative_path != target_artifact.get("relative_path"):
        issues.append(
            VerificationIssue(
                code="fault_target_path_mismatch",
                identity=f"artifact:{target_artifact_id}",
                message="controlled fault path differs from the target artifact",
            )
        )
        return
    try:
        content = _resolve_artifact_path(artifact_root, relative_path).read_bytes()
        byte_offset = int(fault.get("byte_offset"))
    except (CutoverEvidenceError, OSError, TypeError, ValueError) as exc:
        issues.append(
            VerificationIssue(
                code="fault_proof_unreadable",
                identity="fault_injection",
                message=f"controlled fault proof is unreadable: {type(exc).__name__}",
            )
        )
        return
    if byte_offset < 0 or byte_offset >= len(content):
        issues.append(
            VerificationIssue(
                code="fault_offset_invalid",
                identity="fault_injection.byte_offset",
                message="controlled byte-flip offset is outside the sealed artifact",
            )
        )
        return
    actual_after = _sha256(content)
    restored = bytearray(content)
    restored[byte_offset] ^= 1
    actual_before = _sha256(bytes(restored))
    if (
        fault.get("fault_id") != FAULT_ARTIFACT_BYTE_FLIP_ID
        or fault.get("failure_code") != "artifact_blob_digest_mismatch"
        or fault.get("after_digest") != actual_after
        or target_artifact.get("content_digest") != actual_after
        or fault.get("before_digest") != actual_before
        or actual_before == actual_after
    ):
        issues.append(
            VerificationIssue(
                code="fault_byte_flip_proof_mismatch",
                identity="fault_injection",
                message="sealed bytes do not prove the declared one-bit digest fault",
            )
        )
    operations = {
        str(item.get("operation_id") or ""): dict(item)
        for item in payload.get("operations") or []
        if isinstance(item, dict)
    }
    source_operation_id = str(fault.get("source_operation_id") or "")
    derivation_operation_id = str(fault.get("derivation_operation_id") or "")
    failure_operation_id = str(fault.get("terminal_failure_operation_id") or "")
    source_operation = operations.get(source_operation_id)
    derivation_operation = operations.get(derivation_operation_id)
    failure_operation = operations.get(failure_operation_id)
    source_artifact_id = str(fault.get("source_artifact_id") or "")
    source_artifact = artifact_map.get(source_artifact_id)
    try:
        source_content = (
            b""
            if source_artifact is None
            else _resolve_artifact_path(
                artifact_root,
                str(source_artifact.get("relative_path") or ""),
            ).read_bytes()
        )
    except (CutoverEvidenceError, OSError):
        source_content = b""
    provider_records = [
        dict(item)
        for item in payload.get("provider_identities") or []
        if isinstance(item, dict)
    ]

    def seals_provider_response(
        artifact_id: object,
        response_digest: object,
    ) -> bool:
        artifact = artifact_map.get(str(artifact_id or ""))
        if artifact is None:
            return False
        try:
            artifact_content = _resolve_artifact_path(
                artifact_root,
                str(artifact.get("relative_path") or ""),
            ).read_bytes()
        except (CutoverEvidenceError, OSError):
            return False
        return _provider_response_bytes_contain_digest(
            artifact_content,
            response_digest,
        )

    provider_proved = any(
        record.get("provider") == "ncbi"
        and record.get("status") == "completed"
        and record.get("canonical_ref_kind") == "controlled_operation"
        and record.get("operation_id") == source_operation_id
        and record.get("cache_hit") is False
        and source_operation is not None
        and record.get("invocation_id") == source_operation.get("backend_run_id")
        and record.get("request_digest") == source_operation.get("params_digest")
        and source_artifact_id in set(record.get("artifact_ids") or [])
        and any(
            seals_provider_response(artifact_id, record.get("response_digest"))
            for artifact_id in record.get("artifact_ids") or []
        )
        for record in provider_records
    )
    source_refs = (
        [] if source_operation is None else source_operation.get("outputs") or []
    )
    source_identity = dict(
        {}
        if source_operation is None
        else source_operation.get("operation_identity_material") or {}
    )
    source_parameters = dict(
        {} if source_operation is None else source_operation.get("parameters") or {}
    )
    derivation_inputs = (
        [] if derivation_operation is None else derivation_operation.get("inputs") or []
    )
    derivation_outputs = (
        []
        if derivation_operation is None
        else derivation_operation.get("outputs") or []
    )
    failure_refs = (
        [] if failure_operation is None else failure_operation.get("inputs") or []
    )
    source_proved = any(
        isinstance(ref, dict)
        and ref.get("artifact_id") == source_artifact_id
        and ref.get("content_digest") == fault.get("source_artifact_digest")
        for ref in source_refs
    ) and (
        source_operation is not None
        and source_operation.get("canonical_ref_kind") == "controlled_operation"
        and source_operation.get("status") == "completed"
        and source_operation.get("terminal") is True
        and source_operation.get("selected_backend") == "provider_http"
        and source_operation.get("route_policy_id")
        == "bio.ncbi_fetch_proteins.provider:v1"
        and source_identity.get("sdk_module") == "bio"
        and source_identity.get("function_name") == "ncbi_fetch_proteins"
        and source_identity.get("route_policy_id")
        == "bio.ncbi_fetch_proteins.provider:v1"
        and source_identity.get("selected_backend") == "provider_http"
        and source_operation.get("params_digest") == canonical_digest(source_parameters)
        and set(source_parameters) == {"accessions", "fields", "output_dir"}
        and source_parameters.get("accessions")
        == list(aox_reference.NCBI_REFERENCE_ACCESSIONS)
        and isinstance(source_parameters.get("fields"), list)
        and all(isinstance(item, str) for item in source_parameters["fields"])
        and isinstance(source_parameters.get("output_dir"), str)
        and bool(str(source_parameters.get("output_dir") or "").strip())
        and source_artifact is not None
        and source_artifact.get("content_digest") == fault.get("source_artifact_digest")
        and _sha256(source_content) == fault.get("source_artifact_digest")
    )
    derivation_identity = dict(
        {}
        if derivation_operation is None
        else derivation_operation.get("operation_identity_material") or {}
    )
    try:
        derived = aox_reference.select_hmm_reference_set(
            source_content,
            expected_contract_id=aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
            expected_contract_digest=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
            ),
            expected_implementation_digest=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            ),
            expected_input_digest=str(fault.get("source_artifact_digest") or ""),
        )
        derivation_bytes_match = derived.to_fasta().encode("utf-8") == bytes(restored)
    except ValueError:
        derivation_bytes_match = False
    derivation_proved = (
        derivation_operation is not None
        and derivation_operation.get("canonical_ref_kind") == "sandbox_calculation"
        and derivation_operation.get("status") == "completed"
        and derivation_operation.get("terminal") is True
        and fault.get("derivation_id")
        == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
        and fault.get("derivation_contract_digest")
        == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        and fault.get("derivation_implementation_digest")
        == aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        and derivation_identity.get("calculation_id") == fault.get("derivation_id")
        and derivation_identity.get("calculation_contract_digest")
        == fault.get("derivation_contract_digest")
        and derivation_identity.get("calculation_implementation_digest")
        == fault.get("derivation_implementation_digest")
        and derivation_inputs
        == [
            {
                "artifact_id": source_artifact_id,
                "content_digest": fault.get("source_artifact_digest"),
            }
        ]
        and derivation_outputs
        == [
            {
                "artifact_id": target_artifact_id,
                "content_digest": actual_before,
            }
        ]
        and source_artifact is not None
        and source_artifact.get("content_digest") == fault.get("source_artifact_digest")
        and derivation_bytes_match
    )
    failure_proved = (
        failure_operation is not None
        and failure_operation.get("canonical_ref_kind") == "controlled_operation"
        and failure_operation.get("status") in {"failed", "recovery_failed"}
        and failure_operation.get("terminal") is True
        and failure_operation.get("failure_code") == "artifact_blob_digest_mismatch"
        and failure_operation.get("selected_backend") == "hpc"
        and failure_operation.get("route_policy_id") == "bio_tools.mafft.hpc:v1"
        and dict(failure_operation.get("operation_identity_material") or {}).get(
            "sdk_module"
        )
        == "bio_tools"
        and dict(failure_operation.get("operation_identity_material") or {}).get(
            "function_name"
        )
        == "mafft"
        and dict(failure_operation.get("operation_identity_material") or {}).get(
            "route_policy_id"
        )
        == "bio_tools.mafft.hpc:v1"
        and dict(failure_operation.get("operation_identity_material") or {}).get(
            "toolchain_id"
        )
        == AOX_TOOLCHAIN_RUNTIME_CONTRACTS["mafft"]["toolchain_id"]
        and fault.get("consumer_tool_id") == "bio_tools.mafft"
        and any(
            isinstance(ref, dict)
            and ref.get("artifact_id") == target_artifact_id
            and ref.get("content_digest") == actual_before
            for ref in failure_refs
        )
    )
    effective_config = dict(
        dict(dict(payload.get("product_path") or {}).get("launch_receipt") or {}).get(
            "effective_config"
        )
        or {}
    )
    configured_runner_contracts = _runner_contract_expectations_from_config(
        effective_config
    )
    expected_consumer_runner_contract = {
        "tool_id": "bio_tools.mafft",
        **dict(configured_runner_contracts.get("bio_tools.mafft") or {}),
    }
    runner_contract_proved = (
        len(expected_consumer_runner_contract) == 4
        and fault.get("consumer_runner_contract_expectation")
        == expected_consumer_runner_contract
    )
    if (
        not provider_proved
        or not source_proved
        or not derivation_proved
        or not failure_proved
        or not runner_contract_proved
        or not source_operation_id
        or not failure_operation_id
        or not derivation_operation_id
        or len({source_operation_id, derivation_operation_id, failure_operation_id})
        != 3
    ):
        issues.append(
            VerificationIssue(
                code="fault_operation_attestation_invalid",
                identity="fault_injection",
                message="controlled fault is not bound to the exact provider source, versioned derivation, and terminal MAFFT consumer",
            )
        )
    _verify_fault_negative_state_closure(
        payload,
        artifact_root=artifact_root,
        artifact_map=artifact_map,
        fault=fault,
        operations=operations,
        issues=issues,
    )


def _verify_fault_negative_state_closure(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    fault: Mapping[str, Any],
    operations: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
    closure_artifact_id = str(fault.get("negative_state_closure_artifact_id") or "")
    closure_artifact = artifact_map.get(closure_artifact_id)
    try:
        content = (
            b""
            if closure_artifact is None
            else _resolve_artifact_path(
                artifact_root,
                str(closure_artifact.get("relative_path") or ""),
            ).read_bytes()
        )
        document = _strict_json_loads(content.decode("utf-8"))
    except (CutoverEvidenceError, OSError, UnicodeDecodeError, ValueError):
        document = None
    if not isinstance(document, dict):
        issues.append(
            VerificationIssue(
                code="fault_negative_state_closure_invalid",
                identity="fault_injection.negative_state_closure_artifact_id",
                message="fault negative-state closure is missing or unreadable",
            )
        )
        return
    closure_value = document.get("negative_state_closure")
    closure = dict(closure_value) if isinstance(closure_value, dict) else {}
    task_receipts = [
        dict(item)
        for item in closure.get("task_receipts") or []
        if isinstance(item, dict)
    ]
    report_states = [
        dict(item)
        for item in closure.get("report_states") or []
        if isinstance(item, dict)
    ]
    draft_states = [
        dict(item)
        for item in closure.get("draft_states") or []
        if isinstance(item, dict)
    ]
    conversation_receipts = [
        dict(item)
        for item in closure.get("conversation_receipts") or []
        if isinstance(item, dict)
    ]
    durable_events = [
        dict(item)
        for item in closure.get("durable_event_receipts") or []
        if isinstance(item, dict)
    ]
    consumer_states = [
        dict(item)
        for item in closure.get("consumer_states") or []
        if isinstance(item, dict)
    ]
    top_tasks = [
        {
            key: item.get(key)
            for key in (
                "task_id",
                "role",
                "kind",
                "status",
                "business_exit",
                "assigned_ref",
                "lane_id",
                "finish_ref",
                "finish_payload_digest",
                "finished_by",
                "evidence_refs",
                "delegation_request_ref",
                "delegation_request_digest",
                "delegation_request",
                "workflow_refs",
                "workflow_manifests",
            )
        }
        for item in payload.get("tasks") or []
        if isinstance(item, dict)
    ]
    failure_operation_id = str(fault.get("terminal_failure_operation_id") or "")
    failure_operation = operations.get(failure_operation_id)
    failure_task_id = (
        "" if failure_operation is None else str(failure_operation.get("task_id") or "")
    )
    execution_task = next(
        (item for item in task_receipts if item.get("task_id") == failure_task_id),
        None,
    )
    expected_consumer_states = sorted(
        (
            {
                "operation_id": operation_id,
                "task_id": operation.get("task_id"),
                "sdk_module": dict(
                    operation.get("operation_identity_material") or {}
                ).get("sdk_module"),
                "function_name": dict(
                    operation.get("operation_identity_material") or {}
                ).get("function_name"),
                "selected_backend": operation.get("selected_backend"),
                "status": operation.get("status"),
                "failure_code": operation.get("failure_code"),
                "operation_identity_digest": operation.get("operation_identity_digest"),
            }
            for operation_id, operation in operations.items()
            if any(
                isinstance(ref, dict)
                and ref.get("artifact_id") == fault.get("target_artifact_id")
                for ref in operation.get("inputs") or []
            )
        ),
        key=lambda item: str(item["operation_id"]),
    )
    cursors = [item.get("cursor") for item in durable_events]
    report = dict(payload.get("report") or {})
    final_answer = dict(payload.get("final_answer") or {})
    final_message_id = str(final_answer.get("message_id") or "")
    assistant_receipts = [
        item for item in conversation_receipts if item.get("role") == "assistant"
    ]
    final_message_matches = (
        bool(final_message_id)
        and closure.get("final_assistant_failure_message_id") == final_message_id
        and closure.get("final_assistant_failure_code")
        == "artifact_blob_digest_mismatch"
        and closure.get("final_assistant_failure_status") == "failed"
        and all(
            marker in str(final_answer.get("content") or "")
            for marker in (
                "failure_code=artifact_blob_digest_mismatch",
                "status=failed",
            )
        )
        and bool(assistant_receipts)
        and assistant_receipts[-1].get("message_id") == final_message_id
        and any(
            item.get("message_id") == final_message_id
            and item.get("content_digest") == final_answer.get("content_digest")
            for item in assistant_receipts
        )
    ) or (
        not final_message_id
        and not str(final_answer.get("content") or "")
        and closure.get("final_assistant_failure_message_id") is None
        and closure.get("final_assistant_failure_code") is None
        and closure.get("final_assistant_failure_status") is None
        and not assistant_receipts
    )
    expected_runner_contract = dict(
        fault.get("consumer_runner_contract_expectation") or {}
    )
    declared_paths = {
        PurePosixPath(str(item.get("relative_path") or "")).as_posix()
        for item in artifact_map.values()
    }
    actual_paths = {
        path.relative_to(artifact_root).as_posix()
        for path in artifact_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    sealed_final_paths: set[str] = set()
    unbound_fixed_evidence_path = False
    for artifact in artifact_map.values():
        if artifact.get("scope") != "formal":
            continue
        provenance = dict(artifact.get("provenance") or {})
        catalog_relative_path = str(provenance.get("catalog_relative_path") or "")
        evidence_relative_path = str(artifact.get("relative_path") or "")
        if catalog_relative_path in _AOX_FIXED_DELIVERABLES:
            sealed_final_paths.add(catalog_relative_path)
        if (
            evidence_relative_path in _AOX_FIXED_DELIVERABLES
            and catalog_relative_path != evidence_relative_path
        ):
            unbound_fixed_evidence_path = True
    expected_observed_prefault_paths = sorted(
        sealed_final_paths & _FAULT_ALLOWED_PREFAULT_DELIVERABLES
    )
    expected_post_fault_paths = sorted(
        sealed_final_paths - _FAULT_ALLOWED_PREFAULT_DELIVERABLES
    )
    file_closure_matches = (
        not unbound_fixed_evidence_path
        and actual_paths == declared_paths
        and closure.get("observed_prefault_deliverable_paths")
        == expected_observed_prefault_paths
        and closure.get("post_fault_final_deliverable_paths")
        == expected_post_fault_paths
        and closure.get("complete_final_deliverable_set_present")
        is (_AOX_FIXED_DELIVERABLES <= sealed_final_paths)
    )
    consumer_runner_contract_matches = (
        len(expected_runner_contract) == 4
        and closure.get("consumer_runner_contract_expectation")
        == expected_runner_contract
    )
    valid = (
        document.get("schema_id") == "aox_blank_world_live_blocker@1"
        and document.get("attempt_kind") == "fault"
        and document.get("failure_code") == "artifact_blob_digest_mismatch"
        and document.get("fault_id") == FAULT_ARTIFACT_BYTE_FLIP_ID
        and closure.get("schema_id") == "aox_fault_negative_state_closure@1"
        and closure.get("session_id")
        == dict(payload.get("product_path") or {}).get("session_id")
        and closure.get("target_artifact_id") == fault.get("target_artifact_id")
        and closure.get("terminal_failure_operation_id") == failure_operation_id
        and closure_artifact is not None
        and closure_artifact.get("content_digest")
        == fault.get("negative_state_closure_digest")
        and _sha256(content) == fault.get("negative_state_closure_digest")
        and task_receipts == top_tasks
        and bool(task_receipts)
        and all(
            item.get("business_exit") == "agent_explicit"
            and item.get("status") in {"completed", "failed", "blocked", "cancelled"}
            and str(item.get("finish_ref") or "")
            and _DIGEST_PATTERN.fullmatch(str(item.get("finish_payload_digest") or ""))
            is not None
            for item in task_receipts
        )
        and execution_task is not None
        and execution_task.get("role") == "executor"
        and execution_task.get("status") in {"failed", "blocked", "cancelled"}
        and not any(
            item.get("role") == "reporter" and item.get("status") == "completed"
            for item in task_receipts
        )
        and not any(
            item.get("status") in {"ready", "published"} for item in report_states
        )
        and not any(
            item.get("status") in {"ready", "published"}
            or item.get("published_report_id")
            for item in draft_states
        )
        and closure.get("success_claim_message_ids") == []
        and final_message_matches
        and consumer_runner_contract_matches
        and bool(durable_events)
        and all(
            set(item)
            == {
                "event_id",
                "cursor",
                "event_type",
                "actor_ref",
                "command_id",
                "payload_digest",
            }
            and str(item.get("event_id") or "")
            and str(item.get("event_type") or "")
            and _DIGEST_PATTERN.fullmatch(str(item.get("payload_digest") or ""))
            is not None
            for item in durable_events
        )
        and all(
            isinstance(cursor, int) and not isinstance(cursor, bool)
            for cursor in cursors
        )
        and cursors == sorted(set(cursors))
        and consumer_states == expected_consumer_states
        and bool(consumer_states)
        and closure.get("successful_alternate_consumer_ids") == []
        and all(
            item.get("status") in {"failed", "recovery_failed"}
            for item in consumer_states
        )
        and expected_post_fault_paths == []
        and file_closure_matches
        and closure.get("complete_final_deliverable_set_present") is False
        and report.get("cutover_eligible") is False
        and report.get("status") == "failed_evidence"
        and report.get("content_artifact_id") == closure_artifact_id
    )
    if not valid:
        issues.append(
            VerificationIssue(
                code="fault_negative_state_closure_invalid",
                identity="fault_injection.negative_state_closure",
                message="sealed fault closure does not prove task/report/conversation/event and consumer non-success state",
            )
        )


def _validate_ledger_transition(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    before_id = before.get("ledger_identity_digest")
    after_id = after.get("ledger_identity_digest")
    if before_id != after_id or _DIGEST_PATTERN.fullmatch(str(before_id or "")) is None:
        raise CutoverEvidenceError(
            "micu_ledger_identity_changed",
            "attempt must use the same persistent MICU ledger before and after",
            details={"identity": "micu_ledger"},
        )
    for snapshot_name, snapshot in (("before", before), ("after", after)):
        _validate_ledger_snapshot(snapshot, snapshot_name=snapshot_name)
    if int(after.get("charged_tokens") or 0) < int(before.get("charged_tokens") or 0):
        raise CutoverEvidenceError(
            "micu_ledger_reset_detected",
            "MICU cumulative charged tokens decreased during an attempt",
            details={"identity": "micu_ledger"},
        )
    if int(after.get("attempt_count") or 0) < int(before.get("attempt_count") or 0):
        raise CutoverEvidenceError(
            "micu_ledger_reset_detected",
            "MICU cumulative attempt count decreased during an attempt",
            details={"identity": "micu_ledger"},
        )


def _validate_micu_attribution(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    product_path: Mapping[str, Any],
) -> None:
    scenario = product_path.get("micu_scenario")
    model = product_path.get("micu_model")
    raw_invocation_ids = product_path.get("micu_invocation_ids")
    if (
        scenario != "aox_blank_world_cutover"
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(raw_invocation_ids, list)
        or not raw_invocation_ids
        or not all(
            isinstance(item, str) and item.strip() for item in raw_invocation_ids
        )
        or len(set(raw_invocation_ids)) != len(raw_invocation_ids)
    ):
        raise CutoverEvidenceError(
            "micu_attribution_invalid",
            "controlled AOX attempt requires explicit scenario, model, and invocation receipts",
            details={"identity": "product_path.micu"},
        )

    aggregate_fields = (
        "attempt_count",
        "charged_tokens",
        "input_tokens",
        "output_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_attempt_count",
        "reservation_overage_tokens",
        "hard_limit_breach_count",
    )

    def grouped_snapshot(
        snapshot: Mapping[str, Any],
        *,
        collection: str,
        identity_field: str,
        identity_value: str,
    ) -> dict[str, int]:
        rows = snapshot.get(collection)
        assert isinstance(rows, list)
        for raw_row in rows:
            assert isinstance(raw_row, dict)
            if raw_row.get(identity_field) == identity_value:
                return {field: int(raw_row[field]) for field in aggregate_fields}
        return {field: 0 for field in aggregate_fields}

    total_delta = {
        field: int(after[field]) - int(before[field]) for field in aggregate_fields
    }
    scenario_before = grouped_snapshot(
        before,
        collection="by_scenario",
        identity_field="scenario",
        identity_value=scenario,
    )
    scenario_after = grouped_snapshot(
        after,
        collection="by_scenario",
        identity_field="scenario",
        identity_value=scenario,
    )
    model_before = grouped_snapshot(
        before,
        collection="by_model",
        identity_field="model",
        identity_value=model,
    )
    model_after = grouped_snapshot(
        after,
        collection="by_model",
        identity_field="model",
        identity_value=model,
    )
    scenario_delta = {
        field: scenario_after[field] - scenario_before[field]
        for field in aggregate_fields
    }
    model_delta = {
        field: model_after[field] - model_before[field] for field in aggregate_fields
    }
    if (
        total_delta["attempt_count"] <= 0
        or total_delta["charged_tokens"] <= 0
        or scenario_delta != total_delta
        or model_delta != total_delta
        or len(raw_invocation_ids) != total_delta["attempt_count"]
    ):
        raise CutoverEvidenceError(
            "micu_usage_unattributed",
            "MICU ledger delta must belong entirely to this AOX scenario and model",
            details={"identity": "micu_ledger"},
        )


def _validate_ledger_snapshot(
    snapshot: Mapping[str, Any],
    *,
    snapshot_name: str,
) -> None:
    integer_fields = (
        "hard_limit_tokens",
        "charged_tokens",
        "remaining_tokens",
        "hard_limit_overage_tokens",
        "attempt_count",
        "estimated_attempt_count",
        "input_tokens",
        "output_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "reservation_overage_tokens",
        "hard_limit_breach_count",
    )
    values: dict[str, int] = {}
    for field in integer_fields:
        value = snapshot.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CutoverEvidenceError(
                "micu_ledger_snapshot_invalid",
                "MICU ledger counters must be non-negative integers",
                details={"identity": f"micu_ledger.{snapshot_name}.{field}"},
            )
        values[field] = value
    limit = values["hard_limit_tokens"]
    charged = values["charged_tokens"]
    if limit != LIVE_MICU_TOKEN_HARD_LIMIT:
        raise CutoverEvidenceError(
            "micu_ledger_limit_invalid",
            "MICU ledger hard limit must remain exactly 500M",
            details={"identity": f"micu_ledger.{snapshot_name}"},
        )
    if (
        charged > limit
        or values["remaining_tokens"] != limit - charged
        or values["hard_limit_overage_tokens"] != 0
        or values["reservation_overage_tokens"] != 0
        or values["hard_limit_breach_count"] != 0
        or charged != values["input_tokens"] + values["output_tokens"]
        or values["input_tokens"]
        != values["actual_input_tokens"] + values["estimated_input_tokens"]
        or values["output_tokens"]
        != values["actual_output_tokens"] + values["estimated_output_tokens"]
        or values["estimated_attempt_count"] > values["attempt_count"]
    ):
        raise CutoverEvidenceError(
            "micu_ledger_budget_invalid",
            "MICU ledger snapshot exceeds or contradicts the fixed cumulative budget",
            details={"identity": f"micu_ledger.{snapshot_name}"},
        )
    aggregate_fields = (
        "attempt_count",
        "charged_tokens",
        "input_tokens",
        "output_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_attempt_count",
        "reservation_overage_tokens",
        "hard_limit_breach_count",
    )
    for collection_name, identity_field in (
        ("by_scenario", "scenario"),
        ("by_model", "model"),
    ):
        raw_rows = snapshot.get(collection_name)
        if not isinstance(raw_rows, list) or not all(
            isinstance(row, dict) for row in raw_rows
        ):
            raise CutoverEvidenceError(
                "micu_ledger_group_invalid",
                "MICU ledger grouped counters must be arrays of objects",
                details={"identity": f"micu_ledger.{snapshot_name}.{collection_name}"},
            )
        seen_identities: set[str] = set()
        group_totals = {field: 0 for field in aggregate_fields}
        for index, raw_row in enumerate(raw_rows):
            row = dict(raw_row)
            group_identity = row.get(identity_field)
            if (
                not isinstance(group_identity, str)
                or not group_identity.strip()
                or group_identity in seen_identities
            ):
                raise CutoverEvidenceError(
                    "micu_ledger_group_invalid",
                    "MICU ledger grouped identities must be unique non-empty text",
                    details={
                        "identity": (
                            f"micu_ledger.{snapshot_name}.{collection_name}[{index}]"
                            f".{identity_field}"
                        )
                    },
                )
            seen_identities.add(group_identity)
            for field in aggregate_fields:
                value = row.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise CutoverEvidenceError(
                        "micu_ledger_group_invalid",
                        "MICU ledger grouped counters must be non-negative integers",
                        details={
                            "identity": (
                                f"micu_ledger.{snapshot_name}.{collection_name}"
                                f"[{index}].{field}"
                            )
                        },
                    )
                group_totals[field] += value
            if (
                row["charged_tokens"] != row["input_tokens"] + row["output_tokens"]
                or row["input_tokens"]
                != row["actual_input_tokens"] + row["estimated_input_tokens"]
                or row["output_tokens"]
                != row["actual_output_tokens"] + row["estimated_output_tokens"]
                or row["estimated_attempt_count"] > row["attempt_count"]
            ):
                raise CutoverEvidenceError(
                    "micu_ledger_group_invalid",
                    "MICU ledger grouped counters are internally contradictory",
                    details={
                        "identity": f"micu_ledger.{snapshot_name}.{collection_name}[{index}]"
                    },
                )
        if any(group_totals[field] != values[field] for field in aggregate_fields):
            raise CutoverEvidenceError(
                "micu_ledger_group_total_mismatch",
                "MICU ledger grouped counters must sum to the cumulative snapshot",
                details={"identity": f"micu_ledger.{snapshot_name}.{collection_name}"},
            )


def _resolve_artifact_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise CutoverEvidenceError(
            "artifact_relative_path_invalid",
            "artifact path must be normalized and relative",
            details={"relative_path": relative_path},
        )
    if root.is_symlink():
        raise CutoverEvidenceError(
            "artifact_symlink_forbidden",
            "authorized artifact root must not be a symlink",
            details={"relative_path": relative_path},
        )
    root_resolved = root.resolve()
    target = root_resolved.joinpath(*relative.parts)
    candidate = root_resolved
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise CutoverEvidenceError(
                "artifact_symlink_forbidden",
                "artifact path must not traverse a symlink",
                details={"relative_path": relative_path},
            )
    resolved_target = target.resolve()
    if root_resolved not in resolved_target.parents:
        raise CutoverEvidenceError(
            "artifact_path_escape",
            "artifact path escapes its authorized root",
            details={"relative_path": relative_path},
        )
    return target


def _is_sensitive_public_key(value: object) -> bool:
    separated = _CAMEL_CASE_BOUNDARY_PATTERN.sub("_", str(value).strip())
    normalized = separated.casefold().replace("-", "_")
    if normalized in _SAFE_PUBLIC_METADATA_KEYS:
        return False
    compact = normalized.replace("_", "")
    return (
        _SENSITIVE_KEY_PATTERN.fullmatch(normalized) is not None
        or compact in _SENSITIVE_COMPACT_KEY_ALIASES
        or compact.endswith(
            (
                "accesstoken",
                "apikey",
                "authorization",
                "clientsecret",
                "connectionstring",
                "cookie",
                "credential",
                "credentials",
                "hostpath",
                "localpath",
                "password",
                "privatekey",
                "privatelocator",
                "refreshtoken",
                "remotepath",
                "runnerconfig",
                "secret",
                "sourceuri",
                "storageuri",
                "token",
            )
        )
    )


def _assert_public_safe(payload: object, *, identity: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            child_identity = f"{identity}.{key_text}"
            if _is_sensitive_public_key(key_text):
                raise CutoverEvidenceError(
                    "public_projection_sensitive_key",
                    "attempt evidence contains a private field",
                    details={"identity": child_identity},
                )
            _assert_public_safe(value, identity=child_identity)
        return
    if isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_public_safe(value, identity=f"{identity}[{index}]")
        return
    if not isinstance(payload, str):
        return
    if _SENSITIVE_VALUE_PATTERN.search(payload):
        raise CutoverEvidenceError(
            "public_projection_secret_value",
            "attempt evidence contains credential-like text",
            details={"identity": identity},
        )
    if _HOST_PATH_PATTERN.search(payload):
        raise CutoverEvidenceError(
            "public_projection_host_path",
            "attempt evidence contains a Host-local path",
            details={"identity": identity},
        )
    if _ENCODED_PRIVATE_LOCATION_PATTERN.search(payload):
        raise CutoverEvidenceError(
            "public_projection_host_path",
            "attempt evidence contains an encoded Host-local path",
            details={"identity": identity},
        )
    if _PRIVATE_LOCATOR_PATTERN.search(payload):
        raise CutoverEvidenceError(
            "public_projection_private_locator",
            "attempt evidence contains a private storage or runner locator",
            details={"identity": identity},
        )
    if _PRIVATE_URL_PATTERN.search(payload):
        raise CutoverEvidenceError(
            "public_projection_private_url",
            "attempt evidence contains a private provider URL",
            details={"identity": identity},
        )
    for url_match in _HTTP_URL_PATTERN.finditer(payload):
        locator = url_match.group(0).rstrip(".,);]")
        try:
            parsed = urlsplit(locator)
        except ValueError:
            parsed = None
        if safe_public_locator(locator) is None:
            raise CutoverEvidenceError(
                "public_projection_private_url",
                "attempt evidence contains a private provider URL",
                details={"identity": identity},
            )
        if parsed is None or parsed.query or parsed.fragment:
            raise CutoverEvidenceError(
                "public_projection_url_query",
                "attempt evidence contains a query-bearing or fragmented URL",
                details={"identity": identity},
            )


def _preloaded_science(root: Path) -> list[str]:
    if not root.is_dir():
        return [root.name]
    matches: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if path.suffix.lower() in _SCIENCE_SUFFIXES or any(
            marker in name for marker in _SCIENCE_NAME_MARKERS
        ):
            matches.append(path.relative_to(root).as_posix())
    return sorted(matches)


def _reject_non_finite(payload: object, *, identity: str) -> None:
    if isinstance(payload, float) and not math.isfinite(payload):
        raise CutoverEvidenceError(
            "canonical_json_non_finite",
            "canonical JSON does not allow NaN or infinity",
            details={"identity": identity},
        )
    if isinstance(payload, dict):
        for key, value in payload.items():
            _reject_non_finite(value, identity=f"{identity}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _reject_non_finite(value, identity=f"{identity}[{index}]")


def _read_bundle_payload(path: Path) -> dict[str, Any]:
    try:
        envelope = _strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    payload = envelope.get("payload") if isinstance(envelope, dict) else None
    return dict(payload) if isinstance(payload, dict) else {}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _strict_json_loads(content: str) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key is forbidden: {key}")
            result[key] = value
        return result

    return json.loads(
        content,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def _write_append_only_bytes(
    destination: Path,
    content: bytes,
    *,
    error_code: str,
    error_message: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise CutoverEvidenceError(
                error_code,
                error_message,
                details={"filename": destination.name},
            ) from exc
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(destination.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "AOX_LAUNCH_RECEIPT_SCHEMA_ID",
    "AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID",
    "AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS",
    "ATTEMPT_BUNDLE_SCHEMA_ID",
    "ATTEMPT_BUNDLE_SCHEMA_ID_V2",
    "ATTEMPT_BUNDLE_SCHEMA_ID_V3",
    "AttemptRunRecord",
    "BlankWorldRoots",
    "BLANK_WORLD_ROOT_PROOF_SCHEMA_ID",
    "CAMPAIGN_DECISION_SCHEMA_ID",
    "canonical_digest",
    "canonical_json_bytes",
    "create_blank_world_roots",
    "CutoverEvidenceError",
    "evaluate_campaign",
    "FAULT_ARTIFACT_BYTE_FLIP_ID",
    "FORMAL_DELEGATION_REQUEST_SCHEMA_ID",
    "KNOWN_POSITIVE_PROBE_SCHEMA_ID",
    "safe_micu_ledger_snapshot",
    "SEALED_SOURCE_TREE_SCHEMA_ID",
    "seal_campaign_decision",
    "VerificationIssue",
    "VerificationResult",
    "TYPED_EMPTY_ARTIFACT_VALIDATION_SCHEMA_ID",
    "verify_sealed_source_tree_envelope",
    "verify_attempt_bundle",
]
