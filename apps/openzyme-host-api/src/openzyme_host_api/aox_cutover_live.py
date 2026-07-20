from __future__ import annotations

import base64
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from typing import Any, Iterator, Literal
import zlib

import httpx
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import build_conversation_projection
from openzyme_core import sandbox_image_record
from openzyme_core.sandbox_runtime import EXEC_POLICY_VERSION
from openzyme_core.sandbox_workspace import DEFAULT_SANDBOX_IMAGE_REF
from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import REPO_ROOT
from openzyme_runtime import safe_public_machine_identifier
from openzyme_runtime import sanitize_public_diagnostic_payload
import uvicorn

from .aox_cutover_evidence import AttemptRunContext
from .aox_cutover_evidence import AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
from .aox_cutover_evidence import AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS
from .aox_cutover_evidence import AOX_TOOLCHAIN_RUNTIME_CONTRACTS
from .aox_cutover_evidence import AOX_HPC_WORKSPACE_BINDING_CONTRACT_ID
from .aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import assert_public_safe_payload
from .aox_cutover_evidence import aox_hpc_workspace_id
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import controlled_operation_digest
from .aox_cutover_evidence import project_formal_delegation_request
from .aox_cutover_evidence import sandbox_calculation_digest
from .aox_cutover_evidence import seal_source_tree_envelope
from .aox_cutover_evidence import typed_empty_artifact_validation_receipt
from .aox_cutover_runtime_config import AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
from .aox_cutover_runtime_config import AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
from .app import HostApiDependencies
from .app import create_app
from .evals import S15_AOX_HMM_FIXED_DELIVERABLES
from .evals import S15_AOX_HMM_FIXED_PROMPT
from .evals import _s15_aox_validate_final_artifacts
from .foundation import build_configured_foundation


LIVE_RUNNER_SCHEMA_ID = "aox_blank_world_live_runner@1"
LIVE_BLOCKER_SCHEMA_ID = "aox_blank_world_live_blocker@1"
BROWSER_APPROVAL_RECEIPT_SCHEMA_ID = "aox_browser_approval_receipt@2"
BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID = "aox_browser_observation_receipt@2"
BROWSER_OBSERVATION_MODE = "chrome_devtools_mcp_file_handoff"
BROWSER_SEALED_PAGE_URL = (
    "loopback://same-process/ui/?project_id=aox-blank-world-cutover"
)
_MAX_BROWSER_SCREENSHOT_BASE64_CHARS = 64 * 1024 * 1024
_MAX_BROWSER_SCREENSHOT_DECODED_BYTES = 64 * 1024 * 1024
FAULT_NEGATIVE_CLOSURE_SCHEMA_ID = "aox_fault_negative_state_closure@1"
MANUAL_APPROVAL_HOST_SCHEMA_ID = "aox_manual_approval_host@1"
MANUAL_APPROVAL_HANDOFF_SCHEMA_ID = "aox_manual_approval_handoff@1"
DEFAULT_UI_DIST = REPO_ROOT / "apps" / "openzyme-web-ui" / "dist"
KNOWN_POSITIVE_PROBE_ID = "independent_globin_provider_hpc_probe"
KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS = ("NP_000509.1", "NP_000549.1")
KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS = ("P68871", "P69905")
_KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS = frozenset(
    {
        ("bio", "ncbi_fetch_proteins"),
        ("bio", "uniprot_fetch"),
        ("bio_tools", "mafft"),
        ("bio_tools", "hmmbuild"),
        ("bio_tools", "cdhit"),
        ("bio_tools", "hmmalign"),
    }
)
S12_OPERATION_IDENTITY_SCHEMA = "openzyme_controlled_operation_s12@1"
SANDBOX_CALCULATION_IDENTITY_SCHEMA = "openzyme_sandbox_calculation_receipt@1"
HMMER_SCORE_FILTERED_ACCESSIONS_PATH = "aox_hmm/hmmer_score_filtered_accessions.csv"
AOX_CANDIDATE_FILTER_ID = "aox_motif_candidate_filter@1"
AOX_CANDIDATE_FILTER_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_CANDIDATE_FILTER_ID,
        "scoring_contract_id": aox_motif.CONTRACT_ID,
        "threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
    }
)
AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID = "aox_upstream_empty_materialization@1"
AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
        "input_contract_id": aox_hmmer.CONTRACT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "outputs": [
            "aox_hmm/hits_len650_700_200.csv",
            "aox_hmm/target.fasta",
        ],
    }
)
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID = "aox_reference_only_scoring_alignment@1"
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "trigger": "empty_scoring_input_targets",
        "input": "aox_hmm/AOX_scoring_input.fasta",
        "output": "aox_hmm/AOX_scoring_alignment.fasta",
    }
)
AOX_EMPTY_MEMBERSHIP_ID = "canonical_empty_cluster_membership@1"
AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_EMPTY_MEMBERSHIP_ID,
        "membership_schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
        "identity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
        "output": "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
    }
)
AOX_DELIVERABLE_NORMALIZATION_ID = "aox_hmm_deliverable_normalization@1"
AOX_DELIVERABLE_NORMALIZATION_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_DELIVERABLE_NORMALIZATION_ID,
        "deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
    }
)

_TERMINAL_OPERATION_STATUSES = {"completed", "failed", "recovery_failed"}
_FAILED_OPERATION_STATUSES = {"failed", "recovery_failed"}
_TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "blocked"}
_FAILED_TASK_STATUSES = {"failed", "cancelled", "blocked"}
_TERMINAL_SANDBOX_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
_SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
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


def _closed_browser_durable_event(
    raw_event: Mapping[str, object],
    *,
    expected_type: Literal[
        "approval.resolved", "sdk_controlled_operation.approval_resolved"
    ],
) -> dict[str, object]:
    event = dict(raw_event)
    payload = dict(event.get("payload") or {})
    payload_keys = (
        {"approval_id", "decision", "actor_ref"}
        if expected_type == "approval.resolved"
        else {
            "approval_id",
            "operation_id",
            "operation_digest",
            "continuation_id",
            "decision",
        }
    )
    cursor = event.get("cursor")
    actor_ref = event.get("actor_ref")
    if expected_type == "approval.resolved" and not actor_ref:
        actor_ref = payload.get("actor_ref")
    if (
        event.get("event_type") != expected_type
        or set(payload) != payload_keys
        or not isinstance(cursor, int)
        or isinstance(cursor, bool)
        or cursor <= 0
        or not str(event.get("event_id") or "")
        or not str(event.get("session_id") or "")
        or not str(event.get("created_at") or "")
        or event.get("schema_version") != "openzyme.v3.event.v1"
        or event.get("visibility") != "public"
        or (actor_ref is not None and not isinstance(actor_ref, str))
        or (
            event.get("command_id") is not None
            and not isinstance(event.get("command_id"), str)
        )
    ):
        raise LiveProductPathError(
            "browser_approval_durable_event_invalid",
            "Chrome approval proof requires the exact closed durable event record",
            details={"event_type": expected_type},
        )
    record = {
        "schema_id": "aox_browser_durable_event@1",
        "cursor": cursor,
        "event_id": str(event["event_id"]),
        "session_id": str(event["session_id"]),
        "event_type": expected_type,
        "schema_version": "openzyme.v3.event.v1",
        "visibility": "public",
        "actor_ref": actor_ref,
        "command_id": event.get("command_id"),
        "created_at": str(event["created_at"]),
        "payload": payload,
        "payload_digest": canonical_digest(payload),
    }
    if set(record) != _BROWSER_DURABLE_EVENT_KEYS:
        raise AssertionError("browser durable event projection is not closed")
    return record


def _strict_json_object(content: str) -> dict[str, object]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    parsed = json.loads(
        content,
        parse_constant=reject_constant,
        object_pairs_hook=pairs_hook,
    )
    if not isinstance(parsed, dict):
        raise ValueError("JSON receipt must be an object")
    return dict(parsed)


def _browser_screenshot_png(
    encoded: object,
) -> tuple[bytes, int, int] | None:
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > _MAX_BROWSER_SCREENSHOT_BASE64_CHARS
    ):
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
    row_bytes = (
        width * channels_by_color_type[color_type] * bit_depth + 7
    ) // 8
    expected_decoded_size = height * (1 + row_bytes)
    if expected_decoded_size > _MAX_BROWSER_SCREENSHOT_DECODED_BYTES:
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


class LiveProductPathError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(f"{code}: {message}")


_SEALED_FAILURE_DETAIL_KEYS = frozenset(
    {
        "cleanup_failure_type",
        "coordination_failure_type",
        "failure_type",
    }
)


def _sealed_failure_details(
    details: Mapping[str, object] | None,
) -> dict[str, str]:
    """Project only bounded machine identifiers into sealed failure evidence."""

    projected: dict[str, str] = {}
    for key in sorted(_SEALED_FAILURE_DETAIL_KEYS):
        value = safe_public_machine_identifier(
            None if details is None else details.get(key),
            fallback=None,
        )
        if value is not None:
            projected[key] = value
    return projected


def _raise_runtime_drain_failures(
    *,
    drain_errors: list[Exception],
    coordination_error: Exception | None,
    cleanup_errors: list[Exception],
) -> None:
    """Raise the most authoritative drain failure without losing diagnostics."""

    cleanup_error = cleanup_errors[0] if cleanup_errors else None
    if drain_errors:
        # The drain command owns the coordinated operation.  Preserve its
        # stable taxonomy even when coordination and cleanup also failed while
        # the command was unwinding.
        error = drain_errors[0]
        secondary_details: dict[str, str] = {}
        if cleanup_error is not None:
            secondary_details["cleanup_failure_type"] = type(cleanup_error).__name__
        if isinstance(error, LiveProductPathError):
            for key, value in secondary_details.items():
                error.details.setdefault(key, value)
            raise error
        raise LiveProductPathError(
            "runtime_drain_command_failed",
            "public runtime drain failed before producing a bounded response",
            details={"failure_type": type(error).__name__, **secondary_details},
        ) from error

    if coordination_error is not None:
        # Cleanup is a mandatory best effort to release a failed worker, but a
        # later cleanup exception must not replace the earlier coordination
        # blocker.  Record only its safe type alongside the primary error.
        cleanup_details = (
            {}
            if cleanup_error is None
            else {"cleanup_failure_type": type(cleanup_error).__name__}
        )
        if isinstance(coordination_error, LiveProductPathError):
            for key, value in cleanup_details.items():
                coordination_error.details.setdefault(key, value)
            raise coordination_error
        raise LiveProductPathError(
            "runtime_drain_coordination_failed",
            "public drain approval coordination failed",
            details={
                "failure_type": type(coordination_error).__name__,
                **cleanup_details,
            },
        ) from coordination_error

    if cleanup_error is not None:
        raise LiveProductPathError(
            "runtime_drain_coordination_cleanup_failed",
            "failed to reject a pending approval during drain cleanup",
            details={"failure_type": type(cleanup_error).__name__},
        ) from cleanup_error


@dataclass(frozen=True, slots=True)
class PublicApiReceipt:
    sequence: int
    method: str
    route: str
    status_code: int
    request_digest: str
    response_digest: str
    response_semantic_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "method": self.method,
            "route": self.route,
            "status_code": self.status_code,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "response_semantic_digest": self.response_semantic_digest,
        }


@dataclass(frozen=True, slots=True)
class SessionDriveResult:
    session_id: str
    purpose: Literal["probe", "formal"]
    state: Literal["completed", "failed", "incomplete", "approval_required"]
    blocker_code: str | None
    workspace: dict[str, Any]
    workspace_response_binding: dict[str, object]
    event_receipt: dict[str, object]
    drain_count: int
    approval_ids: tuple[str, ...]
    browser_approval_receipt: dict[str, object] | None = None
    browser_observation_receipt: dict[str, object] | None = None

    def safe_summary(self) -> dict[str, object]:
        task_items = list(
            dict(self.workspace.get("task_board") or {}).get("items") or []
        )
        operations = list(
            dict(self.workspace.get("runtime_state") or {}).get("controlled_operations")
            or []
        )
        return {
            "session_id": self.session_id,
            "purpose": self.purpose,
            "state": self.state,
            "blocker_code": self.blocker_code,
            "drain_count": self.drain_count,
            "approval_count": len(self.approval_ids),
            "browser_approval_observed": self.browser_approval_receipt is not None,
            "browser_approval_receipt_digest": (
                None
                if self.browser_approval_receipt is None
                else canonical_digest(self.browser_approval_receipt)
            ),
            "browser_observation_observed": (
                self.browser_observation_receipt is not None
            ),
            "browser_observation_receipt_digest": (
                None
                if self.browser_observation_receipt is None
                else canonical_digest(self.browser_observation_receipt)
            ),
            "task_count": len(task_items),
            "projected_operation_count": len(operations),
            "workspace_digest": canonical_digest(self.workspace),
            "event_receipt": dict(self.event_receipt),
        }


@dataclass(frozen=True, slots=True)
class _DrainCoordinationResult:
    workspace: dict[str, Any]
    workspace_response_binding: dict[str, object]
    approval_ids: tuple[str, ...]
    browser_approval_receipt: dict[str, object] | None
    fault_receipt: FaultInjectionReceipt | None


@dataclass(frozen=True, slots=True)
class _LiveDriveOutcome:
    kind: Literal["failure", "fault", "positive"]
    api_receipts: tuple[PublicApiReceipt, ...]
    health: dict[str, object]
    probe: SessionDriveResult | None
    formal: SessionDriveResult | None
    fault: FaultInjectionReceipt | None = None
    blocker: dict[str, object] | None = None


def _terminal_browser_page_state(
    formal: SessionDriveResult,
) -> dict[str, object]:
    approval = dict(formal.browser_approval_receipt or {})
    conversation = [
        dict(item)
        for item in formal.workspace.get("conversation") or []
        if isinstance(item, dict)
    ]
    assistant_messages = [
        item for item in conversation if item.get("role") == "assistant"
    ]
    reports = [
        dict(item)
        for item in formal.workspace.get("reports") or []
        if isinstance(item, dict)
    ]
    scientific_evidence = dict(formal.workspace.get("scientific_evidence") or {})
    operations = [
        dict(item)
        for item in scientific_evidence.get("operations") or []
        if isinstance(item, dict)
    ]
    observed_operation = next(
        (
            item
            for item in operations
            if item.get("operation_id") == approval.get("operation_id")
        ),
        None,
    )
    page_state = {
        "session_id": formal.session_id,
        "approval_id": approval.get("approval_id"),
        "operation_id": approval.get("operation_id"),
        "operation_digest": approval.get("operation_digest"),
        "approval_present": any(
            isinstance(item, dict)
            and item.get("approval_id") == approval.get("approval_id")
            for item in formal.workspace.get("pending_approvals") or []
        ),
        "operation_status": (
            None if observed_operation is None else observed_operation.get("status")
        ),
        "final_master_response_id": (
            None if not assistant_messages else assistant_messages[-1].get("message_id")
        ),
        "report_id": None if not reports else reports[-1].get("report_id"),
        "report_status": None if not reports else reports[-1].get("status"),
        "scientific_evidence_digest": canonical_digest(scientific_evidence),
        "workspace_digest": canonical_digest(formal.workspace),
        "workspace_response_binding": dict(formal.workspace_response_binding),
        "event_stream_digest": formal.event_receipt.get("event_stream_digest"),
        "event_last_cursor": formal.event_receipt.get("last_cursor"),
        "event_response_binding": dict(
            formal.event_receipt.get("public_response_binding") or {}
        ),
    }
    if (
        page_state["approval_present"] is not False
        or observed_operation is None
        or not str(page_state["final_master_response_id"] or "")
        or not str(page_state["report_id"] or "")
        or not str(page_state["report_status"] or "")
    ):
        raise LiveProductPathError(
            "browser_observation_page_state_incomplete",
            "formal public workspace lacks the terminal UI state required for Chrome proof",
        )
    return page_state


@dataclass(frozen=True, slots=True)
class FaultInjectionReceipt:
    source_artifact_id: str
    source_artifact_digest: str
    target_artifact_id: str
    target_relative_path: str
    source_operation_id: str
    terminal_failure_operation_id: str
    derivation_id: str
    derivation_contract_digest: str
    derivation_implementation_digest: str
    consumer_tool_id: str
    byte_offset: int
    before_digest: str
    after_digest: str
    failure_code: str


@dataclass(frozen=True, slots=True)
class ProbeAttestation:
    probe: dict[str, object]
    approvals: tuple[dict[str, object], ...]
    operations: tuple[dict[str, object], ...]
    artifacts: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class CatalogArtifactCopy:
    record: dict[str, object]
    content: bytes
    content_digest: str


@dataclass(frozen=True, slots=True)
class PrimaryPubmedEvidence:
    sources: tuple[object, ...]
    invocation: object
    artifact: SessionArtifactRecord
    researcher_task: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class MicuAttemptReceipt:
    record_id: int
    scenario: str
    model: str

    @property
    def invocation_id(self) -> str:
        return f"micu_ledger_attempt_{self.record_id}"


@dataclass(slots=True)
class _HostMutationTracker:
    """Track server-side mutation lifetime across client disconnects."""

    app: Any
    _condition: threading.Condition = field(
        default_factory=threading.Condition,
        init=False,
        repr=False,
    )
    _active: int = field(default=0, init=False)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        method = str(scope.get("method") or "") if isinstance(scope, dict) else ""
        tracked = method in {"POST", "PUT", "PATCH", "DELETE"}
        if tracked:
            with self._condition:
                self._active += 1
                self._condition.notify_all()
        try:
            await self.app(scope, receive, send)
        finally:
            if tracked:
                with self._condition:
                    self._active -= 1
                    self._condition.notify_all()

    def wait_until_idle(self) -> None:
        with self._condition:
            self._condition.wait_for(lambda: self._active == 0)


@dataclass(slots=True)
class _LoopbackHost:
    """Expose one attempt app to the driver and Chrome without a second Host."""

    app: Any
    request_timeout_seconds: float
    startup_timeout_seconds: float = 15.0
    shutdown_timeout_seconds: float = 15.0
    _socket: socket.socket | None = None
    _server: uvicorn.Server | None = None
    _thread: threading.Thread | None = None
    _client: httpx.Client | None = None
    _mutation_tracker: _HostMutationTracker | None = None
    _failure: BaseException | None = None
    base_url: str = ""

    def __enter__(self) -> httpx.Client:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.set_inheritable(True)
        self._socket = listener
        port = int(listener.getsockname()[1])
        self.base_url = f"http://127.0.0.1:{port}"
        tracker = _HostMutationTracker(self.app)
        self._mutation_tracker = tracker
        server = uvicorn.Server(
            uvicorn.Config(
                tracker,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
                lifespan="on",
                timeout_graceful_shutdown=5,
            )
        )
        self._server = server

        def run() -> None:
            try:
                server.run(sockets=[listener])
            except BaseException as exc:  # pragma: no cover - OS/server boundary
                self._failure = exc

        thread = threading.Thread(
            target=run,
            name="aox-cutover-loopback-host",
            daemon=False,
        )
        self._thread = thread
        thread.start()
        deadline = time.monotonic() + self.startup_timeout_seconds
        while not server.started:
            if self._failure is not None or not thread.is_alive():
                self._retire_server_thread()
                self._close_listener()
                raise LiveProductPathError(
                    "browser_approval_host_start_failed",
                    "same-process loopback Host exited before it became ready",
                    details={
                        "failure_type": (
                            None
                            if self._failure is None
                            else type(self._failure).__name__
                        )
                    },
                )
            if time.monotonic() >= deadline:
                self._retire_server_thread()
                self._close_listener()
                raise LiveProductPathError(
                    "browser_approval_host_start_timeout",
                    "same-process loopback Host did not become ready in time",
                )
            time.sleep(0.05)
        try:
            client = httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.request_timeout_seconds),
            )
            self._client = client
            _emit_operator_record(
                {
                    "schema_id": MANUAL_APPROVAL_HOST_SCHEMA_ID,
                    "status": "ready",
                    "process_id": os.getpid(),
                    "ui_url": (
                        f"{self.base_url}/ui/?project_id=aox-blank-world-cutover"
                    ),
                }
            )
            return client
        except BaseException:
            if self._client is not None:
                try:
                    self._client.close()
                except BaseException:
                    pass
            self._retire_server_thread()
            self._close_listener()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        del exc, traceback
        if self._server is not None:
            self._server.should_exit = True
        client_close_failure: BaseException | None = None
        if self._client is not None:
            try:
                self._client.close()
            except BaseException as close_exc:
                client_close_failure = close_exc
        if self._mutation_tracker is not None:
            self._mutation_tracker.wait_until_idle()
        self._retire_server_thread()
        if self._mutation_tracker is not None:
            self._mutation_tracker.wait_until_idle()
        self._close_listener()
        if client_close_failure is not None and exc_type is None:
            raise LiveProductPathError(
                "browser_approval_host_client_close_failed",
                "loopback Host client failed to close before server retirement",
                details={"failure_type": type(client_close_failure).__name__},
            ) from client_close_failure
        return False

    def _retire_server_thread(self) -> None:
        """Do not return mutable attempt state while the Host can still write.

        The finite shutdown timeout is only a graceful-shutdown allowance.
        Python cannot safely kill a stuck in-process server thread, so after
        requesting Uvicorn's force-exit path this boundary deliberately waits
        without a timeout.  Bounded fatal retirement requires the separately
        documented process-isolated attempt supervisor.
        """

        if self._server is not None:
            self._server.should_exit = True
        if self._thread is None:
            return
        self._thread.join(timeout=self.shutdown_timeout_seconds)
        if self._thread.is_alive() and self._server is not None:
            self._server.force_exit = True
        if self._thread.is_alive():
            self._thread.join()

    def _close_listener(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None


class _PublicHostClient:
    """Closed public route surface used by the campaign driver.

    Repository access is deliberately absent.  Durable repositories are read by
    the collector after public commands have completed; they are never used to
    advance a session or manufacture product state.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._receipts: list[PublicApiReceipt] = []
        self._receipt_lock = threading.Lock()
        self._next_receipt_sequence = 1
        self._inflight_sequences: set[int] = set()
        self._failed_sequences: set[int] = set()
        self._thread_state = threading.local()

    @property
    def receipts(self) -> tuple[PublicApiReceipt, ...]:
        with self._receipt_lock:
            return tuple(sorted(self._receipts, key=lambda item: item.sequence))

    @property
    def sealed_receipts(self) -> tuple[PublicApiReceipt, ...]:
        with self._receipt_lock:
            if self._inflight_sequences or self._failed_sequences:
                raise LiveProductPathError(
                    "public_api_receipt_chain_incomplete",
                    "public API receipt chain has unfinished or failed requests",
                    details={
                        "inflight_count": len(self._inflight_sequences),
                        "failed_count": len(self._failed_sequences),
                    },
                )
            receipts = tuple(sorted(self._receipts, key=lambda item: item.sequence))
        if [item.sequence for item in receipts] != list(
            range(1, len(receipts) + 1)
        ):
            raise LiveProductPathError(
                "public_api_receipt_chain_incomplete",
                "public API receipt chain has an unfinalized sequence gap",
            )
        return receipts

    @property
    def failure_receipts(self) -> tuple[PublicApiReceipt, ...]:
        """Return completed responses for a non-eligible failure artifact.

        Failed request sequences remain absent so the artifact cannot be
        mistaken for a closed eligible chain, while the original blocker can be
        reported instead of being overwritten by the sealing guard.
        """

        with self._receipt_lock:
            if self._inflight_sequences:
                raise LiveProductPathError(
                    "public_api_receipt_chain_incomplete",
                    "failure receipt snapshot still has in-flight requests",
                    details={"inflight_count": len(self._inflight_sequences)},
                )
            return tuple(sorted(self._receipts, key=lambda item: item.sequence))

    @property
    def last_receipt(self) -> PublicApiReceipt:
        receipt = getattr(self._thread_state, "last_receipt", None)
        if not isinstance(receipt, PublicApiReceipt):
            raise LiveProductPathError(
                "public_api_response_receipt_missing",
                "current thread has no public API response receipt to bind",
            )
        return receipt

    @property
    def base_url(self) -> str:
        value = getattr(self._client, "base_url", "")
        return str(value).rstrip("/")

    def get_json(
        self,
        route: str,
        *,
        _timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self._require_route("GET", route)
        sequence = self._reserve_sequence()
        try:
            response = self._client_get(route, timeout_seconds=_timeout_seconds)
            self._record(
                "GET",
                route,
                None,
                response.content,
                response.status_code,
                sequence=sequence,
            )
        except Exception as exc:
            self._fail_sequence(sequence)
            if isinstance(exc, httpx.HTTPError):
                raise LiveProductPathError(
                    "host_public_api_transport_failed",
                    "Host public API GET transport failed",
                    details={
                        "route": route.split("?", 1)[0],
                        "failure_type": type(exc).__name__,
                    },
                ) from exc
            raise
        self._raise_for_status(route, response.status_code, response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise LiveProductPathError(
                "public_api_response_invalid",
                "Host public API returned a non-object response",
                details={"route": route, "status_code": response.status_code},
            )
        return dict(payload)

    def get_events(
        self,
        session_id: str,
        *,
        _timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        events = self.get_event_records(
            session_id,
            _timeout_seconds=_timeout_seconds,
        )
        response_binding = self.response_binding(
            self.last_receipt, semantic_value=list(events)
        )
        event_types = [str(event.get("event_type") or "") for event in events]
        event_ids = [str(event.get("event_id") or "") for event in events]
        cursors = [
            int(event["cursor"])
            for event in events
            if isinstance(event.get("cursor"), int)
        ]
        return {
            "event_stream_digest": canonical_digest(events),
            "event_count": len(event_ids),
            "event_ids_digest": canonical_digest(event_ids),
            "event_types": sorted(set(event_types)),
            "last_cursor": max(cursors, default=0),
            "event_records": [dict(event) for event in events],
            "event_records_digest": canonical_digest(events),
            "public_response_binding": response_binding,
        }

    @staticmethod
    def response_binding(
        receipt: PublicApiReceipt,
        *,
        semantic_value: object,
    ) -> dict[str, object]:
        semantic_digest = canonical_digest(semantic_value)
        if receipt.response_semantic_digest != semantic_digest:
            raise LiveProductPathError(
                "public_api_response_semantic_digest_mismatch",
                "public API response receipt does not bind the returned semantic value",
                details={"sequence": receipt.sequence, "route": receipt.route},
            )
        return {
            "receipt_sequence": receipt.sequence,
            "route": receipt.route,
            "response_digest": receipt.response_digest,
            "response_semantic_digest": semantic_digest,
        }

    def get_event_records(
        self,
        session_id: str,
        *,
        after_cursor: int = 0,
        _timeout_seconds: float | None = None,
    ) -> tuple[dict[str, Any], ...]:
        route = f"/v3/sessions/{session_id}/events?replay=1&after_cursor={after_cursor}"
        self._require_route("GET", route)
        sequence = self._reserve_sequence()
        try:
            response = self._client_get(route, timeout_seconds=_timeout_seconds)
            self._record(
                "GET",
                route,
                None,
                response.content,
                response.status_code,
                sequence=sequence,
            )
        except Exception as exc:
            self._fail_sequence(sequence)
            if isinstance(exc, httpx.HTTPError):
                raise LiveProductPathError(
                    "host_public_api_transport_failed",
                    "Host public event replay transport failed",
                    details={
                        "route": route.split("?", 1)[0],
                        "failure_type": type(exc).__name__,
                    },
                ) from exc
            raise
        self._raise_for_status(route, response.status_code, response)
        events: list[dict[str, Any]] = []
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line.removeprefix("data: "))
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(dict(event))
        return tuple(events)

    def post_json(
        self,
        route: str,
        payload: Mapping[str, object],
        *,
        idempotency_key: str,
        _request_started: threading.Event | None = None,
        _timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self._require_route("POST", route)
        body = dict(payload)
        sequence = self._reserve_sequence()
        if _request_started is not None:
            _request_started.set()
        try:
            response = self._client_post(
                route,
                body=body,
                idempotency_key=idempotency_key,
                timeout_seconds=_timeout_seconds,
            )
            self._record(
                "POST",
                route,
                body,
                response.content,
                response.status_code,
                sequence=sequence,
            )
        except Exception as exc:
            self._fail_sequence(sequence)
            if isinstance(exc, httpx.HTTPError):
                raise LiveProductPathError(
                    "host_public_api_transport_failed",
                    "Host public API POST transport failed",
                    details={
                        "route": route.split("?", 1)[0],
                        "failure_type": type(exc).__name__,
                    },
                ) from exc
            raise
        self._raise_for_status(route, response.status_code, response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise LiveProductPathError(
                "public_api_response_invalid",
                "Host public API returned a non-object response",
                details={"route": route, "status_code": response.status_code},
            )
        return dict(parsed)

    def _record(
        self,
        method: str,
        route: str,
        payload: Mapping[str, object] | None,
        response: bytes,
        status_code: int,
        *,
        sequence: int | None = None,
    ) -> None:
        canonical_route = route.split("?", 1)[0]
        request_payload: Mapping[str, object] = (
            {} if payload is None else dict(payload)
        )
        if method == "GET" and canonical_route.endswith("/events"):
            match = re.fullmatch(
                r"(?P<path>/v3/sessions/[A-Za-z0-9._-]+/events)"
                r"\?replay=1&after_cursor=(?P<cursor>0|[1-9][0-9]*)",
                route,
            )
            if match is None:
                raise LiveProductPathError(
                    "event_replay_query_invalid",
                    "event reads must bind canonical replay and after_cursor semantics",
                )
            after_cursor = int(match.group("cursor"))
            canonical_route = (
                f"{match.group('path')}?replay=1&after_cursor={after_cursor}"
            )
            request_payload = {"replay": True, "after_cursor": after_cursor}
        elif method == "POST" and canonical_route.endswith("/messages"):
            body = dict(request_payload)
            message = str(body.get("message") or "")
            skill_keys = body.get("skill_keys")
            request_payload = {
                "message_digest": _sha256(message.encode("utf-8")),
                "skill_keys": (
                    [str(item) for item in skill_keys]
                    if isinstance(skill_keys, list)
                    else []
                ),
            }
        response_semantic_digest = self._response_semantic_digest(
            method=method,
            route=canonical_route,
            response=response,
            status_code=status_code,
        )
        if sequence is None:
            sequence = self._reserve_sequence()
        with self._receipt_lock:
            receipt = PublicApiReceipt(
                sequence=sequence,
                method=method,
                route=canonical_route,
                status_code=status_code,
                request_digest=canonical_digest(request_payload),
                response_digest=_sha256(response),
                response_semantic_digest=response_semantic_digest,
            )
            self._receipts.append(receipt)
            self._inflight_sequences.discard(sequence)
        self._thread_state.last_receipt = receipt

    def _reserve_sequence(self) -> int:
        with self._receipt_lock:
            sequence = self._next_receipt_sequence
            self._next_receipt_sequence += 1
            self._inflight_sequences.add(sequence)
        return sequence

    def _fail_sequence(self, sequence: int) -> None:
        with self._receipt_lock:
            if sequence in self._inflight_sequences:
                self._inflight_sequences.remove(sequence)
                self._failed_sequences.add(sequence)

    def _client_get(self, route: str, *, timeout_seconds: float | None) -> Any:
        if timeout_seconds is not None and isinstance(self._client, httpx.Client):
            return self._client.get(route, timeout=timeout_seconds)
        return self._client.get(route)

    def _client_post(
        self,
        route: str,
        *,
        body: Mapping[str, object],
        idempotency_key: str,
        timeout_seconds: float | None,
    ) -> Any:
        kwargs: dict[str, object] = {
            "json": dict(body),
            "headers": {"Idempotency-Key": idempotency_key},
        }
        if timeout_seconds is not None and isinstance(self._client, httpx.Client):
            kwargs["timeout"] = timeout_seconds
        return self._client.post(route, **kwargs)

    @staticmethod
    def _response_semantic_digest(
        *,
        method: str,
        route: str,
        response: bytes,
        status_code: int,
    ) -> str:
        if 200 <= status_code < 300 and method == "GET" and "/events?" in route:
            events: list[dict[str, object]] = []
            try:
                text = response.decode("utf-8")
                for line in text.splitlines():
                    if not line or line.startswith((":", "event: ", "id: ", "retry: ")):
                        continue
                    if not line.startswith("data: "):
                        raise ValueError("unexpected SSE line")
                    item = _strict_json_object(line.removeprefix("data: "))
                    events.append(item)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                raise LiveProductPathError(
                    "public_event_response_invalid",
                    "successful event replay response is not a closed JSON SSE stream",
                    details={"failure_type": type(exc).__name__},
                ) from exc
            return canonical_digest(events)
        try:
            parsed = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            if 200 <= status_code < 300:
                raise LiveProductPathError(
                    "public_api_response_invalid",
                    "successful Host public API response is not canonical JSON",
                    details={"route": route},
                )
            return _sha256(response)
        return canonical_digest(parsed)

    def _raise_for_status(self, route: str, status_code: int, response: Any) -> None:
        if status_code < 400:
            return
        error_code = "host_public_api_error"
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict) and error.get("code"):
                    error_code = str(error["code"])
        except (ValueError, TypeError):
            pass
        raise LiveProductPathError(
            error_code,
            "Host public API command failed",
            details={"route": route.split("?", 1)[0], "status_code": status_code},
        )

    @staticmethod
    def _require_route(method: str, route: str) -> None:
        path = route.split("?", 1)[0]
        segments = [segment for segment in path.split("/") if segment]
        permitted = False
        if method == "GET" and path == "/v3/runtime/health":
            permitted = True
        elif method == "POST" and path == "/v3/sessions":
            permitted = True
        elif len(segments) == 4 and segments[:2] == ["v3", "sessions"]:
            permitted = method == "GET" and segments[3] in {"workspace", "events"}
            permitted = permitted or (method == "POST" and segments[3] == "messages")
        elif len(segments) == 5 and segments[:2] == ["v3", "sessions"]:
            permitted = method == "POST" and segments[3:] == ["runtime", "drain"]
        elif len(segments) == 4 and segments[:2] == ["v3", "approvals"]:
            permitted = method == "POST" and segments[3] == "resolve"
        if not permitted:
            raise LiveProductPathError(
                "noncanonical_api_route_forbidden",
                "live cutover driver attempted a noncanonical Host route",
                details={"method": method, "route": path},
            )


@dataclass(slots=True)
class LiveAoxAttemptRunner:
    settings: OpenZymeSettings = field(repr=False)
    ledger_path: Path = field(repr=False)
    effective_config: Mapping[str, object] | None = None
    approval_mode: Literal["auto", "chrome-once"] = "auto"
    timeout_seconds: float = AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    max_drains: int = 120
    max_signals_per_drain: int = 10
    max_steps_per_agent: int = 16
    browser_poll_interval_seconds: float = 0.5
    browser_approval_timeout_seconds: float = 300.0
    browser_completion_hold_seconds: float = 60.0
    browser_observation_submission_timeout_seconds: float = 180.0
    ui_dist_dir: Path = DEFAULT_UI_DIST
    browser_observation_receipt_path: Path | None = None

    def __post_init__(self) -> None:
        if (
            self.timeout_seconds <= 0
            or self.max_drains <= 0
            or self.browser_poll_interval_seconds <= 0
            or self.browser_approval_timeout_seconds <= 0
            or self.browser_completion_hold_seconds < 0
            or self.browser_observation_submission_timeout_seconds <= 0
        ):
            raise ValueError("live attempt timeout and max_drains must be positive")
        if (
            self.approval_mode == "chrome-once"
            and not (self.ui_dist_dir / "index.html").is_file()
        ):
            raise LiveProductPathError(
                "browser_approval_ui_missing",
                "chrome-once requires the built Web UI dist for the same Host app",
            )
        configured_ledger = Path(
            self.settings.test.live_llm.token_ledger_path
        ).expanduser()
        if configured_ledger.resolve() != self.ledger_path.expanduser().resolve():
            raise LiveProductPathError(
                "micu_ledger_configuration_mismatch",
                "campaign ledger must be the exact ledger charged by the live LLM factory",
                details={
                    "configured_ledger_identity": canonical_digest(
                        {"path": str(configured_ledger.resolve())}
                    ),
                    "campaign_ledger_identity": canonical_digest(
                        {"path": str(self.ledger_path.expanduser().resolve())}
                    ),
                },
            )

    def __call__(self, context: AttemptRunContext) -> dict[str, Any]:
        preflight_blocker = self._settings_blocker(context)
        if preflight_blocker is not None:
            return self._failure_evidence(
                context,
                blocker=preflight_blocker,
                api_receipts=(),
                health={},
                probe=None,
                formal=None,
            )

        micu_record_ids_before = _micu_record_ids(self.ledger_path)
        provider = SQLiteRepositoryProvider(str(context.roots.sqlite_path))
        foundation = build_configured_foundation(
            settings=self.settings,
            token_scenario_override="aox_blank_world_cutover",
        )
        dependencies = HostApiDependencies(
            foundation=foundation,
            v3_repository_provider=provider,
            v3_background_runtime_enabled=False,
            v3_sandbox_workspace_root=context.roots.sandbox_root,
            v3_artifact_blob_root=context.roots.blob_root,
        )
        browser_gate_enabled = self._browser_gate_enabled(context)
        app = create_app(
            dependencies,
            **({"ui_dist_dir": self.ui_dist_dir} if browser_gate_enabled else {}),
        )
        outcome: _LiveDriveOutcome | None = None
        drive_error: Exception | None = None
        with self._host_client(
            app, browser_gate_enabled=browser_gate_enabled
        ) as raw_client:
            api = _PublicHostClient(raw_client)
            try:
                outcome = self._drive_live_attempt(
                    context,
                    api=api,
                    provider=provider,
                    browser_gate_enabled=browser_gate_enabled,
                )
            except Exception as exc:
                drive_error = exc

        # Evidence and ledger-after collection must occur only after the
        # loopback Host has retired every server-side drain handler.
        if drive_error is not None:
            raise drive_error
        if outcome is None:
            raise LiveProductPathError(
                "live_product_path_outcome_missing",
                "live attempt Host exited without a drive outcome",
            )
        if outcome.kind == "positive":
            if outcome.probe is None or outcome.formal is None:
                raise AssertionError("positive live outcome lacks probe/formal state")
            return self._positive_evidence(
                context,
                provider=provider,
                api_receipts=outcome.api_receipts,
                health=outcome.health,
                probe=outcome.probe,
                formal=outcome.formal,
                micu_record_ids_before=micu_record_ids_before,
            )
        if outcome.kind == "fault":
            if (
                outcome.probe is None
                or outcome.formal is None
                or outcome.fault is None
            ):
                raise AssertionError("fault live outcome lacks terminal state")
            return self._fault_evidence(
                context,
                provider=provider,
                api_receipts=outcome.api_receipts,
                health=outcome.health,
                probe=outcome.probe,
                formal=outcome.formal,
                fault=outcome.fault,
                micu_record_ids_before=micu_record_ids_before,
            )
        return self._failure_evidence(
            context,
            blocker=outcome.blocker
            or {
                "code": "live_product_path_failed",
                "message": "live product path failed without a structured blocker",
            },
            provider=provider,
            api_receipts=outcome.api_receipts,
            health=outcome.health,
            probe=outcome.probe,
            formal=outcome.formal,
        )

    def _drive_live_attempt(
        self,
        context: AttemptRunContext,
        *,
        api: _PublicHostClient,
        provider: SQLiteRepositoryProvider,
        browser_gate_enabled: bool,
    ) -> _LiveDriveOutcome:
        probe: SessionDriveResult | None = None
        formal: SessionDriveResult | None = None
        fault: FaultInjectionReceipt | None = None
        health: dict[str, Any] = {}
        try:
            health = api.get_json("/v3/runtime/health")
            health_blocker = self._health_blocker(health)
            if health_blocker is not None:
                return _LiveDriveOutcome(
                    kind="failure",
                    blocker=dict(health_blocker),
                    api_receipts=api.sealed_receipts,
                    health=_safe_health(health),
                    probe=None,
                    formal=None,
                )
            self._bootstrap_sandbox_runtime_identity(
                provider,
                health=health,
                identity=context.identity,
            )

            probe_session_id = f"sess_probe_{context.roots.attempt_id}"
            probe = self._run_session(
                api,
                provider,
                session_id=probe_session_id,
                purpose="probe",
                objective="Bounded AOX provider and HPC known-positive health probe.",
                message=self._probe_prompt(context),
                workflow_refs=(),
                fault_enabled=False,
                fault_blob_root=None,
                browser_gate_enabled=False,
            )[0]
            if probe.state != "completed":
                return _LiveDriveOutcome(
                    kind="failure",
                    blocker={
                        "code": probe.blocker_code
                        or "known_positive_probe_incomplete",
                        "message": (
                            "independent NCBI/UniProt and four-tool globin probe "
                            "did not complete"
                        ),
                    },
                    api_receipts=api.sealed_receipts,
                    health=_safe_health(health),
                    probe=probe,
                    formal=None,
                )

            formal_session_id = f"sess_formal_{context.roots.attempt_id}"
            formal, fault = self._run_session(
                api,
                provider,
                session_id=formal_session_id,
                purpose="formal",
                objective=(
                    "Run the canonical blank-world AOX/HMM product path and publish "
                    "a source-linked scientific report."
                ),
                message=self._formal_prompt(context),
                workflow_refs=(context.identity["workflow_ref"],),
                fault_enabled=context.roots.attempt_kind == "fault",
                fault_blob_root=context.roots.blob_root,
                browser_gate_enabled=browser_gate_enabled,
            )
            if context.roots.attempt_kind == "fault":
                if fault is not None and formal.state == "failed":
                    return _LiveDriveOutcome(
                        kind="fault",
                        api_receipts=api.sealed_receipts,
                        health=_safe_health(health),
                        probe=probe,
                        formal=formal,
                        fault=fault,
                    )
                return _LiveDriveOutcome(
                    kind="failure",
                    blocker={
                        "code": "controlled_fault_not_observed",
                        "message": (
                            "formal path did not prove the configured "
                            "artifact-digest fault"
                        ),
                    },
                    api_receipts=api.sealed_receipts,
                    health=_safe_health(health),
                    probe=probe,
                    formal=formal,
                )
            blocker = self._positive_blocker(
                provider,
                formal,
                browser_gate_required=browser_gate_enabled,
            )
            if blocker is not None:
                return _LiveDriveOutcome(
                    kind="failure",
                    blocker=dict(blocker),
                    api_receipts=api.sealed_receipts,
                    health=_safe_health(health),
                    probe=probe,
                    formal=formal,
                )
            if formal.browser_approval_receipt is not None:
                expected_page_state = _terminal_browser_page_state(formal)
                observation_ready_started = time.monotonic()
                observation_ready_wall_ns = time.time_ns()
                observation_not_before_wall_ns = observation_ready_wall_ns + int(
                    round(self.browser_completion_hold_seconds * 1_000_000_000)
                )
                _emit_operator_record(
                    {
                        "schema_id": MANUAL_APPROVAL_HANDOFF_SCHEMA_ID,
                        "status": "ready_for_completion_observation",
                        "session_id": formal.session_id,
                        "hold_seconds": self.browser_completion_hold_seconds,
                        "observation_submission_timeout_seconds": (
                            self.browser_observation_submission_timeout_seconds
                        ),
                        "observation_ready_at_unix_ns": observation_ready_wall_ns,
                        "receipt_not_before_unix_ns": observation_not_before_wall_ns,
                        "receipt_write_protocol": (
                            "after receipt_not_before_unix_ns write a mode-0600 "
                            "sibling temp, fsync, atomically install no-replace, "
                            "then fsync the parent directory"
                        ),
                        "workspace_digest": canonical_digest(formal.workspace),
                        "event_receipt": formal.event_receipt,
                        "expected_page_state": expected_page_state,
                        "expected_page_state_digest": canonical_digest(
                            expected_page_state
                        ),
                        "browser_observation_mode": BROWSER_OBSERVATION_MODE,
                        "browser_observation_receipt_schema_id": (
                            BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
                        ),
                        "sealed_page_url": formal.browser_approval_receipt.get(
                            "page_url"
                        ),
                        "host_process_id": formal.browser_approval_receipt.get(
                            "host_process_id"
                        ),
                        "served_ui_dist_digest": formal.browser_approval_receipt.get(
                            "served_ui_dist_digest"
                        ),
                        "browser_observation_challenge": (
                            formal.browser_approval_receipt.get(
                                "observation_challenge"
                            )
                        ),
                        "browser_observation_receipt_path": (
                            None
                            if self.browser_observation_receipt_path is None
                            else str(self.browser_observation_receipt_path)
                        ),
                    }
                )
                formal = replace(
                    formal,
                    browser_observation_receipt=self._wait_for_browser_observation(
                        formal,
                        observation_ready_started=observation_ready_started,
                        observation_ready_wall_ns=observation_ready_wall_ns,
                    ),
                )
            return _LiveDriveOutcome(
                kind="positive",
                api_receipts=api.sealed_receipts,
                health=_safe_health(health),
                probe=probe,
                formal=formal,
            )
        except LiveProductPathError as exc:
            blocker: dict[str, object] = {
                "code": exc.code,
                "message": _safe_message(exc),
            }
            failure_details = _sealed_failure_details(exc.details)
            if failure_details:
                blocker["details"] = failure_details
            return _LiveDriveOutcome(
                kind="failure",
                blocker=blocker,
                api_receipts=api.failure_receipts,
                health=_safe_health(health) if health else {},
                probe=probe,
                formal=formal,
            )

    def _browser_gate_enabled(self, context: AttemptRunContext) -> bool:
        return (
            self.approval_mode == "chrome-once"
            and context.roots.attempt_kind == "positive"
            and context.attempt_number == 1
        )

    @contextmanager
    def _host_client(
        self,
        app: Any,
        *,
        browser_gate_enabled: bool,
    ) -> Iterator[Any]:
        del browser_gate_enabled
        with _LoopbackHost(
            app=app,
            request_timeout_seconds=self.timeout_seconds,
        ) as client:
            yield client

    def _run_session(
        self,
        api: _PublicHostClient,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        purpose: Literal["probe", "formal"],
        objective: str,
        message: str,
        workflow_refs: tuple[str, ...],
        fault_enabled: bool,
        fault_blob_root: Path | None,
        browser_gate_enabled: bool,
    ) -> tuple[SessionDriveResult, FaultInjectionReceipt | None]:
        api.post_json(
            "/v3/sessions",
            {
                "session_id": session_id,
                "project_id": "aox-blank-world-cutover",
                "objective": objective,
                "title": f"AOX blank-world {purpose}",
            },
            idempotency_key=f"{session_id}:create",
        )
        api.post_json(
            f"/v3/sessions/{session_id}/messages",
            {"message": message, "skill_keys": list(workflow_refs)},
            idempotency_key=f"{session_id}:entry-message",
        )
        started = time.monotonic()
        approval_ids: list[str] = []
        browser_approval_receipt: dict[str, object] | None = None
        fault_receipt: FaultInjectionReceipt | None = None
        last_workspace: dict[str, Any] = {}
        last_workspace_response_binding: dict[str, object] = {}
        for drain_number in range(1, self.max_drains + 1):
            if time.monotonic() - started > self.timeout_seconds:
                break
            pre_drain_events = api.get_event_records(
                session_id,
                _timeout_seconds=max(
                    0.001, started + self.timeout_seconds - time.monotonic()
                ),
            )
            pre_drain_cursor = max(
                (
                    int(event["cursor"])
                    for event in pre_drain_events
                    if isinstance(event.get("cursor"), int)
                    and not isinstance(event.get("cursor"), bool)
                ),
                default=0,
            )
            coordination = self._coordinate_runtime_drain(
                api,
                provider,
                session_id=session_id,
                drain_number=drain_number,
                started=started,
                pre_event_cursor=pre_drain_cursor,
                prior_approval_ids=frozenset(approval_ids),
                browser_gate_enabled=browser_gate_enabled,
                browser_approval_receipt=browser_approval_receipt,
                fault_enabled=fault_enabled,
                fault_blob_root=fault_blob_root,
                fault_receipt=fault_receipt,
            )
            last_workspace = coordination.workspace
            last_workspace_response_binding = (
                coordination.workspace_response_binding
            )
            approval_ids.extend(coordination.approval_ids)
            browser_approval_receipt = coordination.browser_approval_receipt
            fault_receipt = coordination.fault_receipt
            state, blocker = self._session_state(
                provider,
                session_id=session_id,
                purpose=purpose,
            )
            if state in {"completed", "failed"}:
                if fault_receipt is not None:
                    fault_receipt = self._complete_fault_receipt(
                        provider,
                        fault_receipt,
                    )
                    if state == "failed" and not self._fault_negative_state_is_closed(
                        provider,
                        session_id=session_id,
                        receipt=fault_receipt,
                    ):
                        continue
                return (
                    SessionDriveResult(
                        session_id=session_id,
                        purpose=purpose,
                        state=state,
                        blocker_code=blocker,
                        workspace=last_workspace,
                        workspace_response_binding=last_workspace_response_binding,
                        event_receipt=api.get_events(
                            session_id,
                            _timeout_seconds=max(
                                0.001,
                                started + self.timeout_seconds - time.monotonic(),
                            ),
                        ),
                        drain_count=drain_number,
                        approval_ids=tuple(approval_ids),
                        browser_approval_receipt=browser_approval_receipt,
                    ),
                    fault_receipt,
                )
        if not last_workspace:
            last_workspace = api.get_json(
                f"/v3/sessions/{session_id}/workspace",
                _timeout_seconds=max(
                    0.001, started + self.timeout_seconds - time.monotonic()
                ),
            )
            last_workspace_response_binding = api.response_binding(
                api.last_receipt, semantic_value=last_workspace
            )
        return (
            SessionDriveResult(
                session_id=session_id,
                purpose=purpose,
                state="incomplete",
                blocker_code=f"{purpose}_runtime_drain_exhausted",
                workspace=last_workspace,
                workspace_response_binding=last_workspace_response_binding,
                event_receipt=api.get_events(
                    session_id,
                    _timeout_seconds=max(
                        0.001, started + self.timeout_seconds - time.monotonic()
                    ),
                ),
                drain_count=self.max_drains,
                approval_ids=tuple(approval_ids),
                browser_approval_receipt=browser_approval_receipt,
            ),
            fault_receipt,
        )

    def _coordinate_runtime_drain(
        self,
        api: _PublicHostClient,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        drain_number: int,
        started: float,
        pre_event_cursor: int,
        prior_approval_ids: frozenset[str],
        browser_gate_enabled: bool,
        browser_approval_receipt: dict[str, object] | None,
        fault_enabled: bool,
        fault_blob_root: Path | None,
        fault_receipt: FaultInjectionReceipt | None,
    ) -> _DrainCoordinationResult:
        """Drive approvals while the bounded drain request remains in flight.

        The current supervised sandbox waits synchronously for each controlled
        operation decision.  The live evidence driver therefore has to observe
        and resolve those requests through the public Host API concurrently with
        the public drain command.  This is a cutover-driver coordination seam,
        not a replacement for the durable runtime/continuation architecture.
        """

        drain_done = threading.Event()
        drain_request_started = threading.Event()
        drain_errors: list[Exception] = []
        deadline = started + self.timeout_seconds

        def post_drain() -> None:
            try:
                api.post_json(
                    f"/v3/sessions/{session_id}/runtime/drain",
                    {
                        "max_signals": self.max_signals_per_drain,
                        "max_steps_per_agent": self.max_steps_per_agent,
                        "auto_enqueue_ready_tasks": False,
                    },
                    idempotency_key=f"{session_id}:drain:{drain_number}",
                    _request_started=drain_request_started,
                    _timeout_seconds=max(0.001, deadline - time.monotonic()),
                )
            except Exception as exc:  # propagated on the coordinating thread
                drain_errors.append(exc)
            finally:
                drain_done.set()

        drain_thread = threading.Thread(
            target=post_drain,
            name=f"aox-cutover-drain-{drain_number}",
            daemon=False,
        )
        drain_thread.start()

        handled = set(prior_approval_ids)
        newly_approved: list[str] = []
        latest_workspace: dict[str, Any] = {}
        latest_binding: dict[str, object] = {}
        coordination_error: Exception | None = None
        cleanup_errors: list[Exception] = []

        try:
            while not drain_request_started.is_set():
                if drain_done.is_set():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LiveProductPathError(
                        "runtime_drain_coordination_timeout",
                        "public runtime drain did not begin before the attempt deadline",
                        details={
                            "session_id": session_id,
                            "drain_number": drain_number,
                        },
                    )
                drain_request_started.wait(
                    timeout=min(self.browser_poll_interval_seconds, remaining)
                )

            while True:
                # A failed drain has no bounded response whose post-response
                # workspace projection needs observing.  Let the stable
                # command-failure branch below report the original exception
                # instead of allowing a follow-up GET failure to mask it as a
                # coordination error.
                if drain_done.is_set() and drain_errors:
                    break
                if time.monotonic() >= deadline:
                    raise LiveProductPathError(
                        "runtime_drain_coordination_timeout",
                        "public runtime drain did not reach a bounded response",
                        details={
                            "session_id": session_id,
                            "drain_number": drain_number,
                        },
                    )

                # The workspace response below must be known to have started
                # after a bounded drain response before it can prove that the
                # response exposed no new approval.  Reading the Event after
                # the GET would leave a race where the drain publishes
                # ``waiting_approval`` between the snapshot and the check.
                drain_was_done = drain_done.is_set()
                latest_workspace = api.get_json(
                    f"/v3/sessions/{session_id}/workspace",
                    _timeout_seconds=max(0.001, deadline - time.monotonic()),
                )
                latest_workspace_receipt = api.last_receipt
                latest_binding = api.response_binding(
                    latest_workspace_receipt, semantic_value=latest_workspace
                )
                pending = [
                    dict(item)
                    for item in latest_workspace.get("pending_approvals") or []
                    if isinstance(item, dict)
                ]
                acted = False
                for approval in pending:
                    approval_id = str(approval.get("approval_id") or "")
                    if not approval_id or approval_id in handled:
                        continue
                    _assert_cutover_operation_budget_before_approval(
                        provider,
                        session_id=session_id,
                        approval_id=approval_id,
                    )
                    if browser_gate_enabled and browser_approval_receipt is None:
                        browser_approval_receipt, latest_workspace = (
                            self._wait_for_browser_approval(
                                api,
                                session_id=session_id,
                                workspace=latest_workspace,
                                workspace_receipt=latest_workspace_receipt,
                                pending_approval=approval,
                                started=started,
                                pre_event_cursor=pre_event_cursor,
                            )
                        )
                        latest_binding = api.response_binding(
                            api.last_receipt, semantic_value=latest_workspace
                        )
                    else:
                        if fault_enabled and fault_receipt is not None:
                            raise LiveProductPathError(
                                "fault_path_additional_approval_forbidden",
                                "fault target was injected but the sandbox requested another approval",
                                details={"approval_id": approval_id},
                            )
                        if fault_enabled:
                            if fault_blob_root is None:
                                raise LiveProductPathError(
                                    "fault_blob_root_missing",
                                    "controlled fault injection lacks its attempt-scoped blob root",
                                )
                            fault_receipt = self._inject_before_hpc_approval(
                                provider,
                                session_id=session_id,
                                approval_id=approval_id,
                                blob_root=fault_blob_root,
                            )
                        api.post_json(
                            f"/v3/approvals/{approval_id}/resolve",
                            {"decision": "approved"},
                            idempotency_key=f"{session_id}:approve:{approval_id}",
                            _timeout_seconds=max(
                                0.001, deadline - time.monotonic()
                            ),
                        )
                    handled.add(approval_id)
                    newly_approved.append(approval_id)
                    acted = True
                    if browser_approval_receipt is not None:
                        break
                if not acted:
                    # A bounded drain may return ``waiting_approval`` after the
                    # approval and continuation have become durable.  Always
                    # inspect the post-response workspace once before leaving
                    # this coordination seam so that the approval can be
                    # resolved and the next drain can resume the continuation.
                    if drain_was_done:
                        break
                    if drain_done.is_set():
                        continue
                    remaining = max(0.0, deadline - time.monotonic())
                    drain_done.wait(
                        timeout=min(self.browser_poll_interval_seconds, remaining)
                    )
        except Exception as exc:
            coordination_error = exc

        if coordination_error is not None and not drain_done.is_set():
            # Once the public receipt/coordination chain is invalid, no later
            # controlled operation may continue scientific execution.  Keep
            # rejecting approvals until the bounded drain request retires or
            # the attempt's existing deadline is reached.  A short, separate
            # cleanup window can expire before a synchronously waiting sandbox
            # publishes its next durable approval and strand the drain worker.
            cleanup_deadline = deadline
            rejected: set[str] = set()
            while not drain_done.is_set() and time.monotonic() < cleanup_deadline:
                try:
                    cleanup_workspace = api.get_json(
                        f"/v3/sessions/{session_id}/workspace",
                        _timeout_seconds=max(
                            0.001, cleanup_deadline - time.monotonic()
                        ),
                    )
                    cleanup_pending = [
                        dict(item)
                        for item in cleanup_workspace.get("pending_approvals") or []
                        if isinstance(item, dict)
                    ]
                    for approval in cleanup_pending:
                        approval_id = str(approval.get("approval_id") or "")
                        if (
                            not approval_id
                            or approval_id in handled
                            or approval_id in rejected
                        ):
                            continue
                        api.post_json(
                            f"/v3/approvals/{approval_id}/resolve",
                            {"decision": "rejected"},
                            idempotency_key=(
                                f"{session_id}:reject-on-coordination-error:{approval_id}"
                            ),
                            _timeout_seconds=max(
                                0.001, cleanup_deadline - time.monotonic()
                            ),
                        )
                        rejected.add(approval_id)
                except Exception as exc:
                    if not cleanup_errors:
                        cleanup_errors.append(exc)
                    # A transient public workspace/resolve failure is only a
                    # bounded secondary cleanup diagnostic.  Retry with the
                    # same idempotency keys so a later approval can still be
                    # rejected and the primary failure can converge cleanly;
                    # retaining repeated exception objects until a long
                    # attempt deadline would provide no additional taxonomy.
                remaining = max(0.0, cleanup_deadline - time.monotonic())
                drain_done.wait(
                    timeout=min(self.browser_poll_interval_seconds, remaining)
                )

        drain_thread.join(timeout=2.0)
        if drain_thread.is_alive():
            # The drain request itself has a finite remaining-attempt transport
            # timeout.  Do not unwind the Host context while that request still
            # owns a server-side runtime call; wait for the bounded request to
            # retire its reservation first.
            drain_thread.join()
        _raise_runtime_drain_failures(
            drain_errors=drain_errors,
            coordination_error=coordination_error,
            cleanup_errors=cleanup_errors,
        )

        latest_workspace = api.get_json(
            f"/v3/sessions/{session_id}/workspace",
            _timeout_seconds=max(0.001, deadline - time.monotonic()),
        )
        latest_binding = api.response_binding(
            api.last_receipt, semantic_value=latest_workspace
        )
        unhandled_pending = [
            str(item.get("approval_id") or "")
            for item in latest_workspace.get("pending_approvals") or []
            if isinstance(item, dict)
            and str(item.get("approval_id") or "") not in handled
        ]
        if unhandled_pending:
            raise LiveProductPathError(
                "runtime_drain_returned_with_unhandled_approval",
                "public runtime drain returned without coordinating a pending approval",
                details={"pending_count": len(unhandled_pending)},
            )
        return _DrainCoordinationResult(
            workspace=latest_workspace,
            workspace_response_binding=latest_binding,
            approval_ids=tuple(newly_approved),
            browser_approval_receipt=browser_approval_receipt,
            fault_receipt=fault_receipt,
        )

    def _wait_for_browser_approval(
        self,
        api: _PublicHostClient,
        *,
        session_id: str,
        workspace: Mapping[str, object],
        workspace_receipt: PublicApiReceipt,
        pending_approval: Mapping[str, object],
        started: float,
        pre_event_cursor: int,
    ) -> tuple[dict[str, object], dict[str, Any]]:
        approval_id = str(pending_approval.get("approval_id") or "")
        operation = dict(pending_approval.get("operation") or {})
        sandbox_run = dict(pending_approval.get("sandbox_run") or {})
        operation_id = str(operation.get("operation_id") or "")
        operation_digest = str(operation.get("operation_digest") or "")
        sandbox_workspace_id = str(
            operation.get("sandbox_workspace_id")
            or sandbox_run.get("sandbox_workspace_id")
            or ""
        )
        sandbox_run_id = str(sandbox_run.get("sandbox_run_id") or "")
        if (
            not approval_id
            or not operation_id
            or _SHA256_DIGEST_PATTERN.fullmatch(operation_digest) is None
            or not sandbox_workspace_id
            or not sandbox_run_id
        ):
            raise LiveProductPathError(
                "browser_approval_identity_incomplete",
                "pending approval lacks the operation and sandbox identity required for Chrome proof",
            )
        if isinstance(pre_event_cursor, bool) or pre_event_cursor < 0:
            raise LiveProductPathError(
                "browser_approval_cursor_invalid",
                "Chrome approval handoff lacks a valid pre-drain durable-event cursor",
            )
        pre_cursor = pre_event_cursor
        workspace_route = f"/v3/sessions/{session_id}/workspace"
        if (
            workspace_receipt.method != "GET"
            or workspace_receipt.route != workspace_route
        ):
            raise LiveProductPathError(
                "browser_approval_pre_workspace_response_unbound",
                "pending approval projection is not bound to its public workspace response",
            )
        pre_workspace_response_binding = api.response_binding(
            workspace_receipt, semantic_value=dict(workspace)
        )
        ui_url = f"{api.base_url}/ui/?project_id=aox-blank-world-cutover"
        sealed_page_url = BROWSER_SEALED_PAGE_URL
        ui_dist_digest = str(
            dict(dict(self.effective_config or {}).get("driver") or {}).get(
                "ui_dist_digest"
            )
            or ""
        )
        if _SHA256_DIGEST_PATTERN.fullmatch(ui_dist_digest) is None:
            raise LiveProductPathError(
                "browser_approval_ui_identity_missing",
                "Chrome approval handoff lacks the sealed built-UI identity",
            )
        observation_challenge = "sha256:" + hashlib.sha256(
            secrets.token_bytes(32)
        ).hexdigest()
        if (
            self.browser_observation_receipt_path is not None
            and self.browser_observation_receipt_path.exists()
        ):
            raise LiveProductPathError(
                "browser_observation_receipt_not_fresh",
                "Chrome observation handoff path already exists before this challenge",
            )
        _emit_operator_record(
            {
                "schema_id": MANUAL_APPROVAL_HANDOFF_SCHEMA_ID,
                "status": "approval_required",
                "process_id": os.getpid(),
                "ui_url": ui_url,
                "sealed_page_url": sealed_page_url,
                "served_ui_dist_digest": ui_dist_digest,
                "browser_observation_receipt_schema_id": (
                    BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
                ),
                "session_id": session_id,
                "approval_id": approval_id,
                "operation_id": operation_id,
                "operation_digest": operation_digest,
                "sandbox_workspace_id": sandbox_workspace_id,
                "sandbox_run_id": sandbox_run_id,
                "pre_event_cursor": pre_cursor,
                "browser_observation_mode": BROWSER_OBSERVATION_MODE,
                "browser_observation_challenge": observation_challenge,
                "browser_observation_receipt_path": (
                    None
                    if self.browser_observation_receipt_path is None
                    else str(self.browser_observation_receipt_path)
                ),
            }
        )
        handoff_started = time.monotonic()
        resolution_event: dict[str, Any] | None = None
        continuation_event: dict[str, Any] | None = None
        event_response_bindings: list[dict[str, object]] = []
        cursor = pre_cursor
        total_attempt_deadline = started + self.timeout_seconds
        browser_deadline = handoff_started + self.browser_approval_timeout_seconds
        deadline = min(total_attempt_deadline, browser_deadline)
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(self.browser_poll_interval_seconds, remaining))
            new_events = api.get_event_records(
                session_id,
                after_cursor=cursor,
                _timeout_seconds=max(0.001, deadline - time.monotonic()),
            )
            event_binding = api.response_binding(
                api.last_receipt, semantic_value=list(new_events)
            )
            event_response_bindings.append(
                {
                    **event_binding,
                    "event_records": [dict(event) for event in new_events],
                    "event_records_digest": canonical_digest(new_events),
                }
            )
            for event in new_events:
                if isinstance(event.get("cursor"), int):
                    cursor = max(cursor, int(event["cursor"]))
                payload = dict(event.get("payload") or {})
                if (
                    event.get("event_type") == "approval.resolved"
                    and payload.get("approval_id") == approval_id
                ):
                    decision = payload.get("decision")
                    if decision is None:
                        # The public activity backfill also projects the full
                        # resolved ApprovalRequest under this event type.  It
                        # carries ``status`` rather than the authenticated
                        # command event's closed ``decision`` payload and is
                        # neither positive nor negative browser proof.
                        continue
                    if decision != "approved":
                        raise LiveProductPathError(
                            "browser_approval_rejected",
                            "Chrome operator rejected the cutover operation",
                        )
                    resolution_event = event
                if (
                    event.get("event_type")
                    == "sdk_controlled_operation.approval_resolved"
                    and payload.get("approval_id") == approval_id
                ):
                    if (
                        payload.get("decision") != "approved"
                        or payload.get("operation_id") != operation_id
                        or payload.get("operation_digest") != operation_digest
                        or not str(payload.get("continuation_id") or "")
                    ):
                        raise LiveProductPathError(
                            "browser_approval_operation_identity_drift",
                            "approval continuation did not preserve the pending operation identity",
                        )
                    continuation_event = event
            if resolution_event is None or continuation_event is None:
                continue
            post_workspace = api.get_json(
                f"/v3/sessions/{session_id}/workspace",
                _timeout_seconds=max(0.001, deadline - time.monotonic()),
            )
            post_workspace_response_binding = api.response_binding(
                api.last_receipt, semantic_value=post_workspace
            )
            still_pending = {
                str(item.get("approval_id") or "")
                for item in post_workspace.get("pending_approvals") or []
                if isinstance(item, dict)
            }
            projected_operations = [
                dict(item)
                for item in dict(post_workspace.get("scientific_evidence") or {}).get(
                    "operations"
                )
                or []
                if isinstance(item, dict)
            ]
            resumed = next(
                (
                    item
                    for item in projected_operations
                    if item.get("operation_id") == operation_id
                ),
                None,
            )
            if approval_id in still_pending:
                continue
            if (
                resumed is None
                or resumed.get("operation_digest") != operation_digest
                or resumed.get("approval_id") != approval_id
                or resumed.get("approval_state") != "approved"
            ):
                raise LiveProductPathError(
                    "browser_approval_projection_identity_drift",
                    "post-approval workspace does not project the same approved operation",
                )
            resolution_payload = dict(resolution_event.get("payload") or {})
            continuation_payload = dict(continuation_event.get("payload") or {})
            resolution_record = _closed_browser_durable_event(
                resolution_event,
                expected_type="approval.resolved",
            )
            continuation_record = _closed_browser_durable_event(
                continuation_event,
                expected_type="sdk_controlled_operation.approval_resolved",
            )
            resolution_cursor = resolution_record.get("cursor")
            continuation_cursor = continuation_record.get("cursor")
            if (
                not isinstance(resolution_cursor, int)
                or isinstance(resolution_cursor, bool)
                or not isinstance(continuation_cursor, int)
                or isinstance(continuation_cursor, bool)
                or not pre_cursor < resolution_cursor < continuation_cursor
            ):
                raise LiveProductPathError(
                    "browser_approval_event_cursor_order_invalid",
                    "Chrome approval durable events do not follow the sealed pre-drain cursor",
                )
            if (
                resolution_record["session_id"] != session_id
                or continuation_record["session_id"] != session_id
            ):
                raise LiveProductPathError(
                    "browser_approval_event_session_drift",
                    "Chrome approval durable events belong to another session",
                )
            target_event_ids = {
                str(resolution_record["event_id"]),
                str(continuation_record["event_id"]),
            }
            relevant_event_bindings = [
                binding
                for binding in event_response_bindings
                if target_event_ids.intersection(
                    str(item.get("event_id") or "")
                    for item in binding.get("event_records") or []
                    if isinstance(item, dict)
                )
            ]
            bound_event_ids = {
                str(item.get("event_id") or "")
                for binding in relevant_event_bindings
                for item in binding.get("event_records") or []
                if isinstance(item, dict)
            }
            if not target_event_ids.issubset(bound_event_ids):
                raise LiveProductPathError(
                    "browser_approval_event_response_unbound",
                    "approval events are not bound to their public event replay responses",
                )
            pre_workspace_snapshot = dict(workspace)
            post_workspace_snapshot = dict(post_workspace)
            receipt = {
                "schema_id": BROWSER_APPROVAL_RECEIPT_SCHEMA_ID,
                "approval_mode": "chrome-once",
                "ui_channel": "same_process_loopback_web_ui",
                "host_process_id": os.getpid(),
                "session_id": session_id,
                "approval_id": approval_id,
                "operation_id": operation_id,
                "operation_digest": operation_digest,
                "sandbox_workspace_id": sandbox_workspace_id,
                "sandbox_run_id": sandbox_run_id,
                "page_url": sealed_page_url,
                "served_ui_dist_digest": ui_dist_digest,
                "observation_challenge": observation_challenge,
                "pre_workspace_snapshot": pre_workspace_snapshot,
                "pre_workspace_digest": canonical_digest(pre_workspace_snapshot),
                "pre_workspace_response_binding": pre_workspace_response_binding,
                "pre_event_cursor": pre_cursor,
                "resolution_event_id": resolution_event.get("event_id"),
                "resolution_event_cursor": resolution_event.get("cursor"),
                "resolution_actor_ref": (
                    resolution_event.get("actor_ref")
                    or resolution_payload.get("actor_ref")
                ),
                "resolution_command_id": resolution_event.get("command_id"),
                "resolution_event_record": resolution_record,
                "continuation_event_id": continuation_event.get("event_id"),
                "continuation_event_cursor": continuation_event.get("cursor"),
                "continuation_id": continuation_payload.get("continuation_id"),
                "continuation_event_record": continuation_record,
                "event_response_bindings": relevant_event_bindings,
                "post_workspace_snapshot": post_workspace_snapshot,
                "post_workspace_digest": canonical_digest(post_workspace_snapshot),
                "post_workspace_response_binding": post_workspace_response_binding,
                "post_operation_status": resumed.get("status"),
                "driver_resolve_route_absent": not any(
                    receipt.method == "POST"
                    and receipt.route == f"/v3/approvals/{approval_id}/resolve"
                    for receipt in api.receipts
                ),
            }
            if not str(receipt["resolution_actor_ref"] or ""):
                raise LiveProductPathError(
                    "browser_approval_actor_missing",
                    "approval resolution event lacks the authenticated operator identity",
                )
            if receipt["driver_resolve_route_absent"] is not True:
                raise LiveProductPathError(
                    "browser_approval_driver_shortcut_detected",
                    "campaign driver resolved the operation reserved for Chrome",
                )
            _emit_operator_record(
                {
                    "schema_id": MANUAL_APPROVAL_HANDOFF_SCHEMA_ID,
                    "status": "approval_observed",
                    "session_id": session_id,
                    "approval_id": approval_id,
                    "operation_id": operation_id,
                    "operation_digest": operation_digest,
                    "receipt_digest": canonical_digest(receipt),
                }
            )
            return receipt, post_workspace
        raise LiveProductPathError(
            "browser_approval_timeout",
            "Chrome approval was not observed before its bounded handoff deadline",
        )

    def _wait_for_browser_observation(
        self,
        formal: SessionDriveResult,
        *,
        observation_ready_started: float,
        observation_ready_wall_ns: int,
    ) -> dict[str, object]:
        approval = dict(formal.browser_approval_receipt or {})
        expected_page_state = _terminal_browser_page_state(formal)
        receipt_path = self.browser_observation_receipt_path
        if receipt_path is None:
            raise LiveProductPathError(
                "browser_observation_receipt_path_missing",
                "chrome-once requires a fresh Chrome DevTools MCP observation receipt path",
            )
        hold_deadline = (
            observation_ready_started + self.browser_completion_hold_seconds
        )
        hold_wall_deadline_ns = observation_ready_wall_ns + int(
            round(self.browser_completion_hold_seconds * 1_000_000_000)
        )
        deadline = (
            hold_deadline + self.browser_observation_submission_timeout_seconds
        )
        raw: dict[str, object] | None = None
        last_failure_type = "receipt_missing"
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now < hold_deadline:
                if receipt_path.exists() or receipt_path.is_symlink():
                    raise LiveProductPathError(
                        "browser_observation_receipt_too_early",
                        "Chrome observation receipt appeared before the Host-held window completed",
                    )
                time.sleep(
                    min(
                        self.browser_poll_interval_seconds,
                        0.25,
                        hold_deadline - now,
                    )
                )
                continue
            if not receipt_path.is_file() or receipt_path.is_symlink():
                time.sleep(min(self.browser_poll_interval_seconds, 0.25))
                continue
            try:
                first_stat = receipt_path.stat()
                first_bytes = receipt_path.read_bytes()
                time.sleep(min(self.browser_poll_interval_seconds, 0.05))
                second_stat = receipt_path.stat()
                second_bytes = receipt_path.read_bytes()
                if (
                    first_stat.st_mtime_ns < hold_wall_deadline_ns
                    or second_stat.st_mtime_ns < hold_wall_deadline_ns
                ):
                    raise LiveProductPathError(
                        "browser_observation_receipt_too_early",
                        "Chrome observation receipt predates the required observation-window end",
                    )
                stable = (
                    first_stat.st_ino == second_stat.st_ino
                    and first_stat.st_size == second_stat.st_size
                    and first_stat.st_mtime_ns == second_stat.st_mtime_ns
                    and first_bytes == second_bytes
                    and bool(second_bytes)
                )
                if not stable:
                    last_failure_type = "unstable_write"
                    continue
                raw = _strict_json_object(second_bytes.decode("utf-8"))
                break
            except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                last_failure_type = type(exc).__name__
                time.sleep(min(self.browser_poll_interval_seconds, 0.1))
        if raw is None:
            code = (
                "browser_observation_receipt_missing"
                if last_failure_type == "receipt_missing"
                else "browser_observation_receipt_invalid"
            )
            raise LiveProductPathError(
                code,
                "Chrome observation receipt was not fresh, stable, and valid after the Host-held window",
                details={"failure_type": last_failure_type},
            )
        expected_keys = {
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
        }
        entries_value = raw.get("console_entries")
        entries = (
            [dict(item) for item in entries_value if isinstance(item, dict)]
            if isinstance(entries_value, list)
            else []
        )
        command = dict(raw.get("devtools_command_receipt") or {})
        page_state = dict(raw.get("page_state") or {})
        transcript_value = raw.get("devtools_transcript")
        transcript = (
            [dict(item) for item in transcript_value if isinstance(item, dict)]
            if isinstance(transcript_value, list)
            else []
        )
        screenshot = _browser_screenshot_png(raw.get("screenshot_png_base64"))
        expected_command_digest = canonical_digest(
            {
                "tool": "chrome_devtools_mcp",
                "command_id": command.get("command_id"),
                "page_target_id": raw.get("page_target_id"),
                "observation_challenge": raw.get("observation_challenge"),
                "action": "observe_console_page_state_and_screenshot",
            }
        )
        expected_response_digest = canonical_digest(
            {
                "page_state": page_state,
                "console_entries": entries,
                "application_error_count": raw.get("application_error_count"),
                "devtools_transcript_digest": canonical_digest(transcript),
                "screenshot_digest": raw.get("screenshot_digest"),
            }
        )
        valid_entries = (
            isinstance(entries_value, list)
            and len(entries) == len(entries_value)
            and [item.get("sequence") for item in entries]
            == list(range(1, len(entries) + 1))
            and all(
                set(item) == {"sequence", "level", "source", "message_digest"}
                and item.get("level")
                in {"debug", "info", "log", "warning"}
                and bool(str(item.get("source") or ""))
                and _SHA256_DIGEST_PATTERN.fullmatch(
                    str(item.get("message_digest") or "")
                )
                is not None
                for item in entries
            )
        )
        screenshot_digest = raw.get("screenshot_digest")
        if (
            set(raw) != expected_keys
            or raw.get("schema_id") != BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
            or raw.get("observation_mode") != BROWSER_OBSERVATION_MODE
            or raw.get("observation_challenge")
            != approval.get("observation_challenge")
            or raw.get("session_id") != formal.session_id
            or raw.get("approval_id") != approval.get("approval_id")
            or raw.get("operation_id") != approval.get("operation_id")
            or raw.get("page_url") != approval.get("page_url")
            or raw.get("host_process_id") != approval.get("host_process_id")
            or raw.get("served_ui_dist_digest")
            != approval.get("served_ui_dist_digest")
            or not str(raw.get("page_target_id") or "")
            or type(raw.get("observation_window_seconds")) not in {int, float}
            or float(raw.get("observation_window_seconds") or -1)
            != float(self.browser_completion_hold_seconds)
            or not valid_entries
            or raw.get("console_entries_digest") != canonical_digest(entries)
            or raw.get("application_error_count") != 0
            or page_state != expected_page_state
            or raw.get("page_state_digest") != canonical_digest(page_state)
            or not isinstance(transcript_value, list)
            or len(transcript) != len(transcript_value)
            or not transcript
            or [item.get("sequence") for item in transcript]
            != list(range(1, len(transcript) + 1))
            or any(
                set(item)
                != {
                    "sequence",
                    "tool",
                    "method",
                    "page_target_id",
                    "request_digest",
                    "response_digest",
                }
                or item.get("tool") != "chrome_devtools_mcp"
                or item.get("page_target_id") != raw.get("page_target_id")
                or _SHA256_DIGEST_PATTERN.fullmatch(
                    str(item.get("request_digest") or "")
                )
                is None
                or _SHA256_DIGEST_PATTERN.fullmatch(
                    str(item.get("response_digest") or "")
                )
                is None
                for item in transcript
            )
            or not {
                "list_console_messages",
                "evaluate_script",
                "take_screenshot",
            }.issubset({str(item.get("method") or "") for item in transcript})
            or raw.get("devtools_transcript_digest")
            != canonical_digest(transcript)
            or set(command)
            != {
                "command_id",
                "tool",
                "command_digest",
                "response_digest",
                "page_target_id",
            }
            or not str(command.get("command_id") or "")
            or command.get("tool") != "chrome_devtools_mcp"
            or command.get("page_target_id") != raw.get("page_target_id")
            or _SHA256_DIGEST_PATTERN.fullmatch(
                str(command.get("command_digest") or "")
            )
            is None
            or command.get("command_digest") != expected_command_digest
            or _SHA256_DIGEST_PATTERN.fullmatch(
                str(command.get("response_digest") or "")
            )
            is None
            or command.get("response_digest") != expected_response_digest
            or screenshot is None
            or _sha256(screenshot[0]) != screenshot_digest
            or raw.get("screenshot_width") != screenshot[1]
            or raw.get("screenshot_height") != screenshot[2]
        ):
            raise LiveProductPathError(
                "browser_observation_receipt_invalid",
                "Chrome observation does not bind the live page or a clean console window",
            )
        host_hold_elapsed = time.monotonic() - observation_ready_started
        if host_hold_elapsed < self.browser_completion_hold_seconds:
            raise LiveProductPathError(
                "browser_observation_hold_incomplete",
                "Host did not preserve the configured post-completion observation window",
            )
        if time.monotonic() > deadline:
            raise LiveProductPathError(
                "browser_observation_submission_timeout",
                "Chrome observation receipt was not accepted within its sealed submission timeout",
            )
        accepted_at_unix_ns = time.time_ns()
        if accepted_at_unix_ns > hold_wall_deadline_ns + int(
            round(
                self.browser_observation_submission_timeout_seconds
                * 1_000_000_000
            )
        ):
            raise LiveProductPathError(
                "browser_observation_submission_timeout",
                "Chrome observation receipt wall-clock acceptance exceeded its sealed submission timeout",
            )
        return {
            **raw,
            "host_observation_hold_seconds": host_hold_elapsed,
            "host_observation_hold_satisfied": True,
            "host_observation_submission_timeout_seconds": (
                self.browser_observation_submission_timeout_seconds
            ),
            "host_observation_ready_at_unix_ns": observation_ready_wall_ns,
            "host_observation_not_before_unix_ns": hold_wall_deadline_ns,
            "host_observation_accepted_at_unix_ns": accepted_at_unix_ns,
        }

    def _session_state(
        self,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        purpose: Literal["probe", "formal"],
    ) -> tuple[Literal["completed", "failed", "incomplete"], str | None]:
        with provider.read() as scope:
            repositories = scope.repositories
            operations = repositories.controlled_operations.list_by_session(session_id)
            tasks = repositories.tasks.list_by_session(session_id)
            sandbox_runs = repositories.sandbox_runs.list_by_session(session_id)
            artifacts = repositories.artifacts.list_by_session(session_id)
            reports = repositories.reports.list_by_session(session_id)
            drafts = repositories.report_drafts.list_by_session(session_id)
            agents = repositories.agents.list_by_session(session_id)
            messages = build_conversation_projection(repositories, session_id)
        failed_operation = next(
            (
                operation
                for operation in operations
                if operation.status.value in _FAILED_OPERATION_STATUSES
            ),
            None,
        )
        if failed_operation is not None:
            return (
                "failed",
                failed_operation.error_code or "controlled_operation_failed",
            )
        failed_task = next(
            (task for task in tasks if task.status.value in _FAILED_TASK_STATUSES),
            None,
        )
        if failed_task is not None:
            return "failed", f"task_{failed_task.status.value}"
        failed_run = next(
            (
                run
                for run in sandbox_runs
                if run.status.value in (_TERMINAL_SANDBOX_STATUSES - {"completed"})
            ),
            None,
        )
        if failed_run is not None:
            return "failed", failed_run.error_code or "sandbox_run_failed"
        assistant_message = any(message.role == "assistant" for message in messages)
        if purpose == "probe":
            completed_functions = {
                (operation.sdk_module, operation.function_name)
                for operation in operations
                if operation.status.value == "completed"
            }
            tasks_terminal = bool(tasks) and all(
                task.status.value in _TERMINAL_TASK_STATUSES for task in tasks
            )
            if (
                _KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS <= completed_functions
                and tasks_terminal
                and assistant_message
            ):
                return "completed", None
            return "incomplete", None
        artifact_paths = {artifact.relative_path for artifact in artifacts}
        task_kinds = {task.kind for task in tasks if task.status.value == "completed"}
        roles = {agent.role for agent in agents}
        report_ready = any(
            report.status.value in {"ready", "published"} for report in reports
        )
        draft_published = any(draft.status.value == "published" for draft in drafts)
        if (
            S15_AOX_HMM_FIXED_DELIVERABLES <= artifact_paths
            and {"research", "execution", "reporting"} <= task_kinds
            and {"researcher", "executor", "reporter"} <= roles
            and report_ready
            and draft_published
            and assistant_message
        ):
            return "completed", None
        return "incomplete", None

    @staticmethod
    def _fault_negative_state_is_closed(
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        receipt: FaultInjectionReceipt,
    ) -> bool:
        with provider.read() as scope:
            repositories = scope.repositories
            operations = repositories.controlled_operations.list_by_session(session_id)
            tasks = repositories.tasks.list_by_session(session_id)
            reports = repositories.reports.list_by_session(session_id)
            drafts = repositories.report_drafts.list_by_session(session_id)
            artifacts = repositories.artifacts.list_by_session(session_id)
            agents = repositories.agents.list_by_session(session_id)
            documents = repositories.engine_documents.list_by_session(session_id)
            conversation = build_conversation_projection(repositories, session_id)
        consumers = [
            operation
            for operation in operations
            if receipt.target_artifact_id in operation.input_artifact_ids
        ]
        target = next(
            (
                operation
                for operation in consumers
                if operation.operation_id == receipt.terminal_failure_operation_id
            ),
            None,
        )
        post_fault_deliverables = S15_AOX_HMM_FIXED_DELIVERABLES - {
            "aox_hmm/AOX_ref21.fasta",
            "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
        }
        agents_by_id = {str(agent.agent_id): str(agent.role) for agent in agents}
        task_by_id = {str(task.task_id): task for task in tasks}
        execution_task = (
            None if target is None else task_by_id.get(str(target.task_id or ""))
        )
        execution_role = (
            ""
            if execution_task is None
            else agents_by_id.get(str(execution_task.assigned_ref or ""), "")
        )
        reporter_completed = any(
            agents_by_id.get(str(task.assigned_ref or ""), "") == "reporter"
            and task.status.value == "completed"
            for task in tasks
        )
        finish_states = {
            str(payload.get("task_id") or ""): str(payload.get("status") or "")
            for document in documents
            if document.document_kind == "task_finish"
            and (payload := dict(document.payload or {}))
        }
        explicit_success_markers = (
            "local live cutover go",
            "cutover-eligible report",
            "aox/hmm completed successfully",
            "published final report",
        )
        assistant_success = any(
            str(message.role) == "assistant"
            and any(
                marker in str(message.content).casefold()
                for marker in explicit_success_markers
            )
            for message in conversation
        )
        assistant_messages = [
            message for message in conversation if str(message.role) == "assistant"
        ]
        final_assistant_failure_bound = not assistant_messages or all(
            marker in str(assistant_messages[-1].content)
            for marker in (
                "failure_code=artifact_blob_digest_mismatch",
                "status=failed",
            )
        )
        return bool(
            target is not None
            and target.status.value in _FAILED_OPERATION_STATUSES
            and target.error_code == "artifact_blob_digest_mismatch"
            and consumers
            and all(
                operation.status.value in _FAILED_OPERATION_STATUSES
                for operation in consumers
            )
            and all(
                operation.status.value in _TERMINAL_OPERATION_STATUSES
                for operation in operations
            )
            and tasks
            and all(task.status.value in _TERMINAL_TASK_STATUSES for task in tasks)
            and all(
                finish_states.get(str(task.task_id)) == task.status.value
                for task in tasks
            )
            and execution_task is not None
            and execution_role == "executor"
            and execution_task.status.value in {"failed", "blocked", "cancelled"}
            and not reporter_completed
            and not any(
                report.status.value in {"ready", "published"} for report in reports
            )
            and not any(
                draft.status.value in {"ready", "published"} for draft in drafts
            )
            and not post_fault_deliverables.intersection(
                artifact.relative_path for artifact in artifacts
            )
            and not assistant_success
            and final_assistant_failure_bound
        )

    def _settings_blocker(
        self,
        context: AttemptRunContext,
    ) -> dict[str, str] | None:
        receipt_path = self.browser_observation_receipt_path
        if self._browser_gate_enabled(context):
            if receipt_path is None:
                return {
                    "code": "browser_observation_receipt_path_missing",
                    "message": "chrome-once requires a fresh observation receipt target before campaign start",
                }
            parent = receipt_path.expanduser().parent
            if (
                receipt_path.exists()
                or receipt_path.is_symlink()
                or not parent.is_dir()
                or parent.is_symlink()
                or not os.access(parent, os.W_OK)
            ):
                return {
                    "code": "browser_observation_receipt_path_invalid",
                    "message": "Chrome observation target must be absent under an existing writable non-symlink directory",
                }
        elif self.approval_mode == "auto" and receipt_path is not None:
            return {
                "code": "browser_observation_receipt_path_unexpected",
                "message": "auto approval mode rejects a Chrome observation receipt target",
            }
        if self.settings.host_api.deployment_profile != "local-dev":
            return {
                "code": "trusted_local_host_required",
                "message": "same-process blank-world runner requires the local trusted-Host profile",
            }
        if not self.settings.test.enable_live_e2e:
            return {
                "code": "live_e2e_not_enabled",
                "message": "OPENZYME_TEST_ENABLE_LIVE_E2E is not enabled",
            }
        if not self.settings.llm.enabled:
            return {
                "code": "live_llm_not_configured",
                "message": "a real configured LLM is required",
            }
        if self.settings.execution.backend != "hpc":
            return {
                "code": "live_hpc_not_configured",
                "message": "the canonical campaign requires execution.backend=hpc",
            }
        if not self.settings.research.pubmed_email:
            return {
                "code": "ncbi_identity_missing",
                "message": "the existing NCBI email identity is not configured",
            }
        return None

    @staticmethod
    def _health_blocker(health: Mapping[str, object]) -> dict[str, str] | None:
        if (
            health.get("schema_version") != "v3.runtime_health.v1"
            or health.get("deployment_profile") != "local-dev"
            or health.get("storage_profile") != "single_process_sqlite"
        ):
            return {
                "code": "runtime_health_invalid",
                "message": "Host runtime health identity does not match the local SQLite campaign contract",
            }
        components = health.get("components")
        if not isinstance(components, dict):
            return {
                "code": "runtime_health_invalid",
                "message": "Host runtime health projection is missing components",
            }
        required = {"model", "execution", "bio_research", "sandbox"}
        unready = sorted(
            name
            for name in required
            if not isinstance(components.get(name), dict)
            or dict(components[name]).get("status") != "ready"
        )
        if unready:
            return {
                "code": "live_runtime_component_unready",
                "message": "required Host runtime components are not ready: "
                + ", ".join(unready),
            }
        return None

    @staticmethod
    def _bootstrap_sandbox_runtime_identity(
        provider: SQLiteRepositoryProvider,
        *,
        health: Mapping[str, object],
        identity: Mapping[str, object],
    ) -> None:
        components = health.get("components")
        sandbox_component = (
            dict(components.get("sandbox") or {})
            if isinstance(components, dict)
            else {}
        )
        details = dict(sandbox_component.get("details") or {})
        actual = {
            "image_digest": str(details.get("image_digest") or ""),
            "sdk_digest": str(details.get("pipeline_sdk_digest") or ""),
        }
        if any(
            _SHA256_DIGEST_PATTERN.fullmatch(value) is None for value in actual.values()
        ):
            raise LiveProductPathError(
                "sandbox_runtime_identity_missing",
                "ready sandbox health lacks canonical image or Pipeline SDK identity",
            )
        expected = {
            "image_digest": str(identity.get("image_digest") or ""),
            "sdk_digest": str(identity.get("sdk_digest") or ""),
        }
        mismatched = sorted(
            key for key, value in actual.items() if expected.get(key) != value
        )
        if mismatched:
            raise LiveProductPathError(
                "campaign_sandbox_identity_mismatch",
                "campaign image or Pipeline SDK identity differs from Host preflight",
                details={"mismatched_fields": mismatched},
            )
        image_ref = (
            f"{DEFAULT_SANDBOX_IMAGE_REF.rsplit(':', maxsplit=1)[0]}@"
            f"{actual['image_digest']}"
        )
        with provider.write() as scope:
            repositories = scope.repositories
            if (
                repositories.sandbox_images.get_default() is not None
                or repositories.sandbox_images.get(DEFAULT_SANDBOX_IMAGE_REF)
                is not None
                or repositories.sandbox_images.get(image_ref) is not None
            ):
                raise LiveProductPathError(
                    "sandbox_image_registry_not_blank",
                    "blank-world SQLite unexpectedly contains a sandbox image identity",
                )
            repositories.sandbox_images.save(
                sandbox_image_record(
                    image_ref=image_ref,
                    image_digest=actual["image_digest"],
                )
            )

    def _positive_blocker(
        self,
        provider: SQLiteRepositoryProvider,
        formal: SessionDriveResult,
        *,
        browser_gate_required: bool,
    ) -> dict[str, str] | None:
        if formal.state != "completed":
            return {
                "code": formal.blocker_code or "canonical_product_path_incomplete",
                "message": "formal product path did not reach its published-report exit",
            }
        if browser_gate_required and formal.browser_approval_receipt is None:
            return {
                "code": "browser_approval_not_observed",
                "message": (
                    "first positive formal path did not preserve a Chrome-observed "
                    "same-operation approval receipt"
                ),
            }
        with provider.read() as scope:
            repositories = scope.repositories
            sources = tuple(
                repositories.research_source_refs.list_by_session(formal.session_id)
            )
            invocations = {
                invocation.invocation_id: invocation
                for invocation in repositories.invocations.list_by_session(
                    formal.session_id
                )
            }
            artifacts = {
                artifact.artifact_id: artifact
                for artifact in repositories.artifacts.list_by_session(
                    formal.session_id
                )
            }
            tasks = tuple(repositories.tasks.list_by_session(formal.session_id))
            agents = tuple(repositories.agents.list_by_session(formal.session_id))
            documents = tuple(
                repositories.engine_documents.list_by_session(formal.session_id)
            )
        try:
            task_receipts, task_ids_by_role = _task_receipts(
                tasks=tasks,
                agents=agents,
                documents=documents,
            )
            _select_primary_pubmed_evidence(
                sources=sources,
                invocations=invocations,
                artifacts=artifacts,
                task_receipts=task_receipts,
                task_ids_by_role=task_ids_by_role,
            )
        except LiveProductPathError as exc:
            return {
                "code": exc.code,
                "message": _safe_message(exc),
            }
        return None

    def _probe_prompt(self, context: AttemptRunContext) -> str:
        return (
            "Run only the independent bounded known-positive probe; do not create AOX "
            "candidates, formal result artifacts, or a report. Delegate exactly one execution "
            "task and use one persistent sandbox, one operation-bearing sandbox.exec run, one "
            "source snapshot, and one Host-supervised HPC workspace for exactly six controlled "
            "operations. The campaign already enforces "
            "provider cache bypass; do not invent unsupported cache flags. Fetch NCBI protein "
            "accessions NP_000509.1 and NP_000549.1, then run MAFFT on that "
            "sealed FASTA and hmmbuild on the MAFFT alignment. Independently fetch UniProt "
            "accessions P68871 and P69905, run CD-HIT with identity 1.0 in protein "
            "mode on that sealed FASTA, then run HMMalign with the real hmmbuild model and the "
            "real CD-HIT clustered UniProt FASTA. Provider calls return a full operation response: "
            "select exactly one file from result_summary.transcript_manifest.files whose "
            "relative_path ends with /provider_parsed/proteins.fasta for NCBI or "
            "/provider_parsed/sequences.fasta for UniProt, and use that file's artifact_id. "
            "Do not select from adapter_result_envelope ID lists or any positional list order. "
            "Use artifacts.provider_file_ref only for provider operation responses and "
            "artifacts.fetched_output_ref only for ws.fetch_outputs responses. Both helpers "
            "already return the terminal canonical artifact_id/content_digest ref; stage or "
            "consume that ref directly and never chain selectors. This probe does not call "
            "artifacts.register, so do not call artifacts.registered_artifact_ref or synthesize "
            "a registration envelope. Before writing the one operation-bearing source, read "
            "docs.read('artifacts') and, only as needed, docs.read('bio'), "
            "docs.read('bio-tools'), or docs.read('sdk-overview') to resolve helper "
            "signatures. Every otherwise-valid sandbox.exec that reaches source preflight, "
            "including Python -c or package/signature inspection, first snapshots the entire "
            "non-empty /workspace/src tree; never spend "
            "the probe's sole run as a read-only environment-inspection shortcut. If runtime "
            "introspection is still necessary, put it in the explicitly authored "
            "operation-bearing source without starting a controlled operation until its local "
            "validation passes. Persist each completed operation response under /workspace/work before "
            "downstream parsing. In that source, pass the provider output directories as the "
            "complete literals output_dir='/workspace/output/provider/ncbi' and "
            "output_dir='/workspace/output/provider/uniprot'. Do not derive either value from "
            "an OUT constant with an f-string, concatenation, os.path.join, or any equivalent "
            "expression. Likewise, never interpolate a sandbox root constant immediately before "
            "a slash-prefixed suffix elsewhere; use a complete /workspace/... literal or join "
            "only relative path components. The raw source snapshot must remain eligible for "
            "self-verifying public-safe sealing. A local failure after the operation-bearing "
            "run starts makes "
            "this @2 probe ineligible: keep checkpoints only as failure evidence, do not start "
            "another controlled operation in this attempt, explicitly fail the task, and let a "
            "fresh attempt retry. Cross-run effect adoption is not available. "
            "The fixed runner templates require exactly these "
            "declared outputs and wire pairs: MAFFT bio_tools/mafft/alignment.fasta as "
            "kind='sequence', format='fasta'; hmmbuild bio_tools/hmmbuild/model.hmm as "
            "kind='result', format='hmm'; CD-HIT bio_tools/cdhit/clustered.fasta as "
            "kind='sequence', format='fasta' plus bio_tools/cdhit/clusters.csv as "
            "kind='result', format='csv'; and HMMalign bio_tools/hmmalign/aligned.fasta as "
            "kind='sequence', format='fasta'. Never declare kind='model'. "
            "Call ws.fetch_outputs for all four run handles, including the terminal HMMalign "
            "run; these fetches do not add controlled operations. Select every fetched artifact "
            "through the unique fetch_refs entry whose declared_output_path exactly matches the "
            "required path, never by registered_artifact_ids or artifacts list order. "
            "Do not call any other provider or HPC tool. "
            "Use the unique HPC workspace label "
            f"{context.roots.hpc_workspace_label!r}. Explicitly finish the task and answer with "
            "the observed two provider and four HPC operation identities. Never use fixture "
            "data, copied formal data, or the AOX reference notebook."
        )

    def _formal_prompt(self, context: AttemptRunContext) -> str:
        workflow_ref = str(context.identity["workflow_ref"])
        execution_task_id = (
            "aox_execution_cutover_"
            + context.roots.hpc_workspace_label.removeprefix("aox-cutover-")
        )
        prompt = (
            S15_AOX_HMM_FIXED_PROMPT
            + " The campaign already enforces evidence-bearing provider cache bypass; do not "
            + "pass or invent unsupported cache flags. Use the unique Host-supervised HPC "
            + f"workspace label {context.roots.hpc_workspace_label!r}. Do not read any prior "
            + "session, historical AOX output, notebook output, fixture, or golden expected result. "
            + "The entry message authorizes exactly one workflow binding. Use exactly the "
            + "canonical task ids aox_research_pubmed_evidence, "
            + execution_task_id
            + ", and aox_final_source_linked_report. On every master wake, reconcile the durable "
            + "task board and inbox against exactly that canonical set: create only a missing "
            + "canonical member, advance any existing member, and never create another, "
            + "suffixed, or replacement task id. When delegating, bind "
            + f"workflow_refs=[{workflow_ref!r}] only to the executor task; researcher and reporter "
            + "must omit workflow_refs or pass an empty list. The executor must use the installed "
            + "versioned callables openzyme_pipeline.aox_reference.select_hmm_reference_set, "
            + "openzyme_pipeline.aox_reference.select_scoring_reference, "
            + "openzyme_pipeline.aox_reference.assemble_scoring_input, "
            + "openzyme_pipeline.aox_hmmer.parse_and_filter_csv, "
            + "openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions, "
            + "openzyme_pipeline.aox_motif.score_aligned_fasta, and "
            + "openzyme_pipeline.aox_similarity.build_similarity_graph with their canonical "
            + "serializers; never reimplement or approximate a pinned calculation. Follow the "
            + "stable signature table in the pinned AOX/HMM SOP and supply every bound "
            + "expected_*_digest. In particular, call join_score_filtered_accessions("
            + "score_filtered_csv, uniprot_fasta, uniprot_metadata_json, ...) and "
            + "build_similarity_graph(candidate_fasta, cdhit_membership_csv, ...) using bytes "
            + "in that positional order; do not guess keyword aliases or serialize result "
            + "internals by hand. Every primary payload accessor named by that table returns "
            + "Python str, while metadata() returns a dict. Encode payload text exactly once "
            + "with UTF-8 before a bytes-only helper such as Path.write_bytes; never pass str "
            + "to a bytes-only writer, and never hand-reimplement the serializer. Provider "
            + "outputs must be selected from the unique result_summary.transcript_manifest.files "
            + "entry ending in /provider_parsed/proteins.fasta for NCBI, "
            + "/provider_parsed/parsed_hits.csv for EBI HMMER, and both "
            + "/provider_parsed/sequences.fasta and /provider_parsed/metadata.json for UniProt. "
            + "Map each closed response to exactly one installed strict helper: provider "
            + "operation response to artifacts.provider_file_ref, ws.fetch_outputs response "
            + "to artifacts.fetched_output_ref, and only the direct response returned by "
            + "artifacts.register to artifacts.registered_artifact_ref. Provider and fetched "
            + "selectors already return terminal canonical artifact_id/content_digest refs; "
            + "never chain selectors, synthesize a registration envelope, or recursively search "
            + "rich provenance. The selected pinned AOX/HMM SOP is already present in the "
            + "executor context; do not reread it. Before the first operation-bearing run, read "
            + "docs.read('artifacts'). /workspace/input is a Host-managed read-only mount to "
            + "the sandbox process: never mkdir, write, copy, or pre-create a materialization "
            + "target or its parents there. artifacts.materialize itself creates the target and "
            + "missing parents through the Host; use /workspace/work for mutable scratch and "
            + "/workspace/output for registerable results. Use docs.read('bio'), "
            + "docs.read('bio-tools'), or "
            + "docs.read('sdk-overview') only as needed to validate uncertain signatures. Every "
            + "otherwise-valid sandbox.exec invocation that reaches source preflight, including "
            + "Python -c, package/signature inspection, and diagnostics, first snapshots the "
            + "entire non-empty /workspace/src tree; never use "
            + "it as a read-only environment-inspection shortcut. If runtime introspection "
            + "remains necessary, first author an explicit inspection source under "
            + "/workspace/src and run that file, accepting that any local nonzero run makes the "
            + "attempt ineligible. Register every normalized final "
            + "FASTA with kind='sequence', format='fasta'; AOX_ref.hmm with kind='result', "
            + "format='hmm'; every normalized final CSV with kind='result', format='csv'; and "
            + "both normalized final JSON files with kind='result', format='json'. Artifact kind "
            + "'model' is invalid: semantic labels such as model, alignment, table, or graph belong "
            + "in format or metadata and must never be invented as kind values. A permitted "
            + "zero-record FASTA keeps kind='sequence', format='fasta' and additionally uses its "
            + "required typed validation profile. Persist each completed "
            + "controlled-operation response under /workspace/work before downstream parsing. "
            + "Current bundle @1 cannot adopt effects across a failed sandbox run: after any "
            + "local nonzero run, preserve checkpoints only as failure evidence, start no more "
            + "controlled operations in that attempt, explicitly fail the task, and let a fresh "
            + "attempt retry. sandbox.exec argv is direct argv with no implicit shell parsing: "
            + "never put heredoc, redirection, or pipeline syntax inside a Python argv element; "
            + "write scripts with sandbox.file.write or sandbox.file.patch and then invoke the "
            + "script path. Use an explicit ['bash', '-lc', '<command>'] argv only when shell "
            + "parsing is intentional. "
            + "Every sandbox.exec invocation whose source may reach the real EBI HMMER wait "
            + "must use timeout_seconds="
            + str(int(AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS))
            + ". Short preflight inspection or post-failure diagnostic commands that cannot "
            + "reach HMMER may use "
            + "shorter bounds. Do not shorten the HMM-capable containment timeout or use a "
            + "later command to justify a duplicate operation. "
            + "Runner templates accept only the "
            + "fixed declarations bio_tools/mafft/alignment.fasta as sequence/fasta, "
            + "bio_tools/hmmbuild/model.hmm as result/hmm, "
            + "bio_tools/cdhit/clustered.fasta as sequence/fasta plus "
            + "bio_tools/cdhit/clusters.csv as result/csv, and "
            + "bio_tools/hmmalign/aligned.fasta as sequence/fasta. Explicitly invalid or "
            + "mismatched kind/format values fail before runner dispatch; never declare "
            + "kind='model'. "
            + "For every bio_tools HPC input, pass the exact dict returned by "
            + "ws.stage_artifact(...) unchanged; never reconstruct it, rename its keys, or "
            + "substitute an artifact-id/digest/workspace-path dict. Select fetched "
            + "runner artifacts only through the unique fetch_refs entry whose "
            + "declared_output_path exactly matches that fixed path. Bind bio.hmmer_search to the "
            + "exact fetched hmmbuild artifact id and content digest. A scientifically derived "
            + "zero-record FASTA is an exact zero-byte file registered with "
            + "validation_profile='fasta_zero_records@1', a stable empty_result_reason, and a "
            + "versioned derivation_contract_id; never write sentinel headers, placeholder "
            + "residues, fake clusters, or fabricated graph rows."
        )
        if context.roots.attempt_kind == "fault":
            prompt += (
                " If the required execution chain fails, do not publish or claim a successful "
                "report: explicitly finish the execution task failed, finish reporting blocked "
                "or cancelled, and bind the final assistant response to the exact observed "
                "structured fields failure_code=artifact_blob_digest_mismatch and "
                "status=failed."
            )
        return prompt

    def _positive_evidence(
        self,
        context: AttemptRunContext,
        *,
        provider: SQLiteRepositoryProvider,
        api_receipts: tuple[PublicApiReceipt, ...],
        health: Mapping[str, object],
        probe: SessionDriveResult,
        formal: SessionDriveResult,
        micu_record_ids_before: set[int],
    ) -> dict[str, Any]:
        evidence = _collect_positive_evidence(
            context,
            provider=provider,
            api_receipts=api_receipts,
            health=health,
            probe=probe,
            formal=formal,
            ledger_path=self.ledger_path,
            micu_record_ids_before=micu_record_ids_before,
        )
        self._attach_effective_config(evidence, context, required=True)
        product_path = dict(evidence["product_path"])
        product_path["public_final_workspace_digest"] = canonical_digest(
            formal.workspace
        )
        product_path["public_final_workspace_response_binding"] = dict(
            formal.workspace_response_binding
        )
        product_path["public_final_event_stream_digest"] = formal.event_receipt.get(
            "event_stream_digest"
        )
        product_path["public_final_event_last_cursor"] = formal.event_receipt.get(
            "last_cursor"
        )
        product_path["public_final_event_response_binding"] = dict(
            formal.event_receipt.get("public_response_binding") or {}
        )
        product_path["public_final_scientific_evidence_digest"] = canonical_digest(
            dict(formal.workspace.get("scientific_evidence") or {})
        )
        launch_receipt = dict(product_path["launch_receipt"])
        public_api_receipts = [item.to_dict() for item in api_receipts]
        launch_receipt.update(
            {
                "campaign_attempt_number": context.attempt_number,
                "approval_mode": self.approval_mode,
                "browser_approval_receipt": formal.browser_approval_receipt,
                "browser_observation_receipt": (
                    formal.browser_observation_receipt
                ),
                "public_api_receipt_digest": canonical_digest(public_api_receipts),
            }
        )
        product_path["public_api_receipts"] = public_api_receipts
        product_path["launch_receipt"] = launch_receipt
        evidence["product_path"] = product_path
        return evidence

    def _attach_effective_config(
        self,
        evidence: dict[str, Any],
        context: AttemptRunContext,
        *,
        required: bool,
    ) -> None:
        config = dict(self.effective_config or {})
        config_digest = canonical_digest(config) if config else ""
        valid = (
            config.get("schema_id") == "aox_blank_world_runtime_config@1"
            and config_digest == context.identity.get("config_digest")
        )
        if required and not valid:
            raise LiveProductPathError(
                "effective_config_attestation_missing",
                "live cutover lacks the canonical effective-config preimage",
            )
        if not valid:
            return
        product_path = dict(evidence.get("product_path") or {})
        product_path["runtime_config_digest"] = config_digest
        launch_receipt = dict(product_path.get("launch_receipt") or {})
        launch_receipt.update(
            {
                "campaign_attempt_number": context.attempt_number,
                "approval_mode": self.approval_mode,
                "effective_config": config,
                "effective_config_digest": config_digest,
            }
        )
        product_path["launch_receipt"] = launch_receipt
        evidence["product_path"] = product_path

    def _failure_evidence(
        self,
        context: AttemptRunContext,
        *,
        blocker: Mapping[str, object],
        provider: SQLiteRepositoryProvider | None = None,
        api_receipts: tuple[PublicApiReceipt, ...],
        health: Mapping[str, object],
        probe: SessionDriveResult | None,
        formal: SessionDriveResult | None,
    ) -> dict[str, Any]:
        blocker_code = str(blocker.get("code") or "live_product_path_failed")
        blocker_record: dict[str, object] = {
            "code": blocker_code,
            "message": str(blocker.get("message") or blocker_code),
        }
        raw_blocker_details = blocker.get("details")
        blocker_details = _sealed_failure_details(
            raw_blocker_details
            if isinstance(raw_blocker_details, Mapping)
            else None
        )
        if blocker_details:
            blocker_record["details"] = blocker_details
        blocker_payload = {
            "schema_id": LIVE_BLOCKER_SCHEMA_ID,
            "runner_schema_id": LIVE_RUNNER_SCHEMA_ID,
            "attempt_id": context.roots.attempt_id,
            "attempt_kind": context.roots.attempt_kind,
            "observed_at": datetime.now(UTC).isoformat(),
            "blocker": blocker_record,
            "root_identity": context.roots.proof["root_identity"],
            "hpc_workspace_label": context.roots.hpc_workspace_label,
            "health": dict(health),
            "probe": None if probe is None else probe.safe_summary(),
            "formal": None if formal is None else formal.safe_summary(),
            "public_api_receipts": [item.to_dict() for item in api_receipts],
        }
        probe_attestation: ProbeAttestation | None = None
        if provider is not None and probe is not None and probe.state == "completed":
            try:
                probe_attestation = _collect_probe_attestation(
                    context,
                    provider=provider,
                    probe=probe,
                )
            except LiveProductPathError as exc:
                blocker_payload["probe_attestation_blocker"] = {
                    "code": exc.code,
                    "message": _safe_message(exc),
                }
        sanitized_blocker_payload = sanitize_public_diagnostic_payload(
            blocker_payload
        )
        if not isinstance(sanitized_blocker_payload, dict):
            raise LiveProductPathError(
                "failure_evidence_sanitization_failed",
                "live failure evidence did not remain a structured object",
            )
        blocker_payload = dict(sanitized_blocker_payload)
        try:
            assert_public_safe_payload(
                blocker_payload,
                identity="live_failure_evidence",
            )
        except CutoverEvidenceError:
            safe_blocker_code = safe_public_machine_identifier(
                blocker_code,
                fallback="live_product_path_failed",
            ) or "live_product_path_failed"
            fallback_blocker: dict[str, object] = {
                "code": safe_blocker_code,
                "message": "[redacted-private-diagnostic]",
            }
            if blocker_details:
                fallback_blocker["details"] = blocker_details
            blocker_payload = {
                "schema_id": LIVE_BLOCKER_SCHEMA_ID,
                "runner_schema_id": LIVE_RUNNER_SCHEMA_ID,
                "attempt_id": context.roots.attempt_id,
                "attempt_kind": context.roots.attempt_kind,
                "observed_at": datetime.now(UTC).isoformat(),
                "blocker": fallback_blocker,
                "root_identity": context.roots.proof["root_identity"],
                "hpc_workspace_label": context.roots.hpc_workspace_label,
                "health": {"status": "redacted"},
                "probe": None,
                "formal": None,
                "public_api_receipts": [],
                "diagnostic_projection": "fail_closed",
            }
            assert_public_safe_payload(
                blocker_payload,
                identity="live_failure_evidence_fallback",
            )
        artifact_id = f"art_live_blocker_{_safe_id(context.roots.attempt_id)}"
        relative_path = "formal/live-product-path-blocker.json"
        content = canonical_json_bytes(blocker_payload) + b"\n"
        _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
        probe_payload = (
            _failed_probe_payload(probe)
            if probe_attestation is None
            else probe_attestation.probe
        )
        fault_injection = None
        failure_code = blocker_code
        if context.roots.attempt_kind == "fault":
            failure_code = "campaign_runner_failed"
            fault_injection = {
                "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                "reached_target_seam": False,
                "expected_failure_observed": False,
                "failure_code": "campaign_runner_failed",
                "blocker_code": blocker_code,
            }
        evidence = {
            "provider_identities": [],
            "engine_invocations": [],
            "toolchain_identities": [],
            "known_positive_probe": probe_payload,
            "product_path": _product_path_failure_receipt(
                context,
                formal=formal,
                api_receipts=api_receipts,
            ),
            "approvals": []
            if probe_attestation is None
            else list(probe_attestation.approvals),
            "operations": []
            if probe_attestation is None
            else list(probe_attestation.operations),
            "tasks": [],
            "artifacts": [
                *(() if probe_attestation is None else probe_attestation.artifacts),
                {
                    "artifact_id": artifact_id,
                    "relative_path": relative_path,
                    "scope": "formal",
                    "origin": "report",
                    "kind": "failure_evidence",
                    "provenance": {
                        "producer": LIVE_RUNNER_SCHEMA_ID,
                        "blocker_code": blocker_code,
                    },
                },
            ],
            "report": {
                "report_id": f"report_failure_{_safe_id(context.roots.attempt_id)}",
                "status": "failed_evidence",
                "cutover_eligible": False,
                "content_artifact_id": artifact_id,
                "content_digest": _sha256(content),
                "artifact_ids": [artifact_id],
                "source_ref_ids": [],
                "claim_source_links": [],
            },
            "final_answer": {
                "message_id": f"msg_failure_{_safe_id(context.roots.attempt_id)}",
                "content": f"AOX blank-world attempt failed closed: {blocker_code}.",
            },
            "scientific_checks": {},
            "warnings": [],
            "degradations": [blocker_code],
            "scientific_outcome": {
                "status": "failed",
                "failure_code": failure_code,
                "blocker_code": blocker_code,
                "cutover_eligible": False,
            },
            "fault_injection": fault_injection,
        }
        self._attach_effective_config(evidence, context, required=False)
        return evidence

    def _fault_evidence(
        self,
        context: AttemptRunContext,
        *,
        provider: SQLiteRepositoryProvider,
        api_receipts: tuple[PublicApiReceipt, ...],
        health: Mapping[str, object],
        probe: SessionDriveResult,
        formal: SessionDriveResult,
        fault: FaultInjectionReceipt,
        micu_record_ids_before: set[int],
    ) -> dict[str, Any]:
        if fault.failure_code != "artifact_blob_digest_mismatch":
            raise LiveProductPathError(
                "controlled_fault_failure_code_mismatch",
                "controlled byte flip did not terminate with the exact digest mismatch",
                details={"observed_failure_code": fault.failure_code},
            )
        evidence = _collect_fault_evidence(
            context,
            provider=provider,
            api_receipts=api_receipts,
            health=health,
            probe=probe,
            formal=formal,
            fault=fault,
            ledger_path=self.ledger_path,
            micu_record_ids_before=micu_record_ids_before,
            effective_config=dict(self.effective_config or {}),
        )
        _attach_fault_public_final_snapshot_artifacts(
            context,
            evidence,
            formal=formal,
        )
        self._attach_effective_config(evidence, context, required=True)
        product_path = dict(evidence["product_path"])
        product_path["public_final_workspace_digest"] = canonical_digest(
            formal.workspace
        )
        product_path["public_final_workspace_response_binding"] = dict(
            formal.workspace_response_binding
        )
        product_path["public_final_event_stream_digest"] = formal.event_receipt.get(
            "event_stream_digest"
        )
        product_path["public_final_event_last_cursor"] = formal.event_receipt.get(
            "last_cursor"
        )
        product_path["public_final_event_response_binding"] = dict(
            formal.event_receipt.get("public_response_binding") or {}
        )
        product_path["public_final_scientific_evidence_digest"] = canonical_digest(
            dict(formal.workspace.get("scientific_evidence") or {})
        )
        launch_receipt = dict(product_path["launch_receipt"])
        public_api_receipts = [item.to_dict() for item in api_receipts]
        launch_receipt.update(
            {
                "campaign_attempt_number": context.attempt_number,
                "approval_mode": self.approval_mode,
                "browser_approval_receipt": None,
                "browser_observation_receipt": None,
                "public_api_receipt_digest": canonical_digest(public_api_receipts),
            }
        )
        product_path["public_api_receipts"] = public_api_receipts
        product_path["launch_receipt"] = launch_receipt
        evidence["product_path"] = product_path
        return evidence

    def _inject_before_hpc_approval(
        self,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        approval_id: str,
        blob_root: Path,
    ) -> FaultInjectionReceipt | None:
        with provider.read() as scope:
            repositories = scope.repositories
            operation = repositories.controlled_operations.get_by_approval_id(
                approval_id
            )
            if operation is None or operation.session_id != session_id:
                raise LiveProductPathError(
                    "fault_approval_operation_unbound",
                    "fault attempt approval is not bound to its formal session operation",
                    details={"approval_id": approval_id},
                )
            if operation.function_name != "mafft":
                return None
            if (
                operation.sdk_module != "bio_tools"
                or operation.selected_backend != "hpc"
                or operation.toolchain_id
                != AOX_TOOLCHAIN_RUNTIME_CONTRACTS["mafft"]["toolchain_id"]
                or not operation.input_artifact_ids
            ):
                raise LiveProductPathError(
                    "fault_target_operation_identity_drift",
                    "mafft fault target does not match the sealed HPC operation identity",
                    details={"operation_id": operation.operation_id},
                )
            operations = repositories.controlled_operations.list_by_session(session_id)
            artifacts = {
                artifact.artifact_id: artifact
                for artifact in repositories.artifacts.list_by_session(session_id)
            }
        targets = [
            artifacts[artifact_id]
            for artifact_id in operation.input_artifact_ids
            if artifact_id in artifacts
            and artifacts[artifact_id].relative_path == "aox_hmm/AOX_ref21.fasta"
        ]
        source_operations = [
            item
            for item in operations
            if item.sdk_module == "bio"
            and item.function_name == "ncbi_fetch_proteins"
            and item.selected_backend == "provider_http"
            and item.status.value == "completed"
        ]
        if len(source_operations) != 1 or len(targets) != 1:
            raise LiveProductPathError(
                "fault_target_artifact_binding_invalid",
                "mafft fault target lacks one canonical AOX reference derivation",
                details={"operation_id": operation.operation_id},
            )
        source_operation = source_operations[0]
        target = targets[0]
        source_artifacts = [
            artifacts[artifact_id]
            for artifact_id in _operation_output_artifact_ids(source_operation)
            if artifact_id in artifacts
            and PurePosixPath(artifacts[artifact_id].relative_path).name
            == "proteins.fasta"
        ]
        if len(source_artifacts) != 1:
            raise LiveProductPathError(
                "fault_source_artifact_binding_invalid",
                "mafft fault target lacks one canonical NCBI source artifact",
                details={"operation_id": operation.operation_id},
            )
        source_artifact = source_artifacts[0]
        path = Path(target.storage_uri)
        source_path = Path(source_artifact.storage_uri)
        resolved_blob_root = blob_root.resolve()
        if (
            not path.is_file()
            or path.is_symlink()
            or not source_path.is_file()
            or source_path.is_symlink()
            or resolved_blob_root not in path.resolve().parents
            or resolved_blob_root not in source_path.resolve().parents
        ):
            raise LiveProductPathError(
                "fault_target_storage_boundary_invalid",
                "fault target is not a regular attempt-scoped artifact",
                details={"operation_id": operation.operation_id},
            )
        content = path.read_bytes()
        source_content = source_path.read_bytes()
        if not content or not source_content:
            raise LiveProductPathError(
                "fault_target_artifact_empty",
                "fault target or its canonical source artifact is empty",
                details={"operation_id": operation.operation_id},
            )
        before_digest = _sha256(content)
        source_digest = _sha256(source_content)
        try:
            target_input_index = operation.input_artifact_ids.index(target.artifact_id)
            declared_target_digest = operation.input_artifact_digests[
                target_input_index
            ]
            derived = aox_reference.select_hmm_reference_set(
                source_content,
                expected_contract_id=(
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                ),
                expected_contract_digest=(
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                ),
                expected_implementation_digest=(
                    aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                ),
                expected_input_digest=source_digest,
            )
        except (ValueError, IndexError) as exc:
            raise LiveProductPathError(
                "fault_target_derivation_invalid",
                "fault target cannot be re-derived from its sealed NCBI source",
                details={"operation_id": operation.operation_id},
            ) from exc
        if (
            declared_target_digest != before_digest
            or derived.to_fasta().encode("utf-8") != content
            or target.run_id != operation.sandbox_run_id
        ):
            raise LiveProductPathError(
                "fault_target_digest_binding_invalid",
                "fault target bytes do not match the approved operation derivation",
                details={"operation_id": operation.operation_id},
            )
        byte_offset = min(4, len(content) - 1)
        mutated = bytearray(content)
        mutated[byte_offset] ^= 1
        path.chmod(0o600)
        try:
            path.write_bytes(bytes(mutated))
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        finally:
            path.chmod(0o444)
        return FaultInjectionReceipt(
            source_artifact_id=source_artifact.artifact_id,
            source_artifact_digest=source_digest,
            target_artifact_id=target.artifact_id,
            target_relative_path=target.relative_path,
            source_operation_id=source_operation.operation_id,
            terminal_failure_operation_id=operation.operation_id,
            derivation_id=(aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID),
            derivation_contract_digest=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
            ),
            derivation_implementation_digest=(
                aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            ),
            consumer_tool_id="bio_tools.mafft",
            byte_offset=byte_offset,
            before_digest=before_digest,
            after_digest=_sha256(bytes(mutated)),
            failure_code="pending",
        )

    @staticmethod
    def _complete_fault_receipt(
        provider: SQLiteRepositoryProvider,
        receipt: FaultInjectionReceipt,
    ) -> FaultInjectionReceipt:
        with provider.read() as scope:
            operation = scope.repositories.controlled_operations.get(
                receipt.terminal_failure_operation_id
            )
        return FaultInjectionReceipt(
            source_artifact_id=receipt.source_artifact_id,
            source_artifact_digest=receipt.source_artifact_digest,
            target_artifact_id=receipt.target_artifact_id,
            target_relative_path=receipt.target_relative_path,
            source_operation_id=receipt.source_operation_id,
            terminal_failure_operation_id=receipt.terminal_failure_operation_id,
            derivation_id=receipt.derivation_id,
            derivation_contract_digest=receipt.derivation_contract_digest,
            derivation_implementation_digest=receipt.derivation_implementation_digest,
            consumer_tool_id=receipt.consumer_tool_id,
            byte_offset=receipt.byte_offset,
            before_digest=receipt.before_digest,
            after_digest=receipt.after_digest,
            failure_code=(
                "operation_missing"
                if operation is None
                else str(operation.error_code or operation.status.value)
            ),
        )


def controlled_operation_identity_material(
    operation: ControlledOperation,
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": operation.adapter_envelope_schema_version,
        "sandbox_workspace_id": operation.sandbox_workspace_id,
        "source_snapshot_digest": operation.source_snapshot_digest,
        "sdk_module": operation.sdk_module,
        "function_name": operation.function_name,
        "params_digest": operation.params_digest,
        "input_artifact_ids": list(operation.input_artifact_ids),
        "input_artifact_digests": list(operation.input_artifact_digests),
        "placement": operation.placement,
        "hpc_workspace_id": operation.hpc_workspace_id,
        "stage_refs": [dict(item) for item in operation.stage_refs],
        "selected_backend": operation.selected_backend,
        "route_reason": operation.route_reason,
        "route_policy_id": operation.route_policy_id,
        "runtime_packaging_id": operation.runtime_packaging_id,
        "toolchain_id": operation.toolchain_id,
        "provider_config_digest": operation.provider_config_digest,
        "resource_class": operation.resource_class,
        "resource_estimate": dict(operation.resource_estimate or {}),
        "expected_outputs": dict(operation.expected_outputs_summary or {}),
        "planned_fetch_intent": dict(operation.planned_fetch_intent or {}),
        "approval_requirement": dict(operation.approval_requirement or {}),
    }
    actual = controlled_operation_digest(material)
    if actual != operation.operation_digest:
        raise LiveProductPathError(
            "controlled_operation_digest_mismatch",
            "durable operation fields do not reproduce the approval-bound S12 digest",
            details={"operation_id": operation.operation_id},
        )
    return material


def _require_attempt_hpc_workspace_binding(
    context: AttemptRunContext,
    operations: tuple[ControlledOperation, ...],
) -> set[str]:
    workspace_ids: set[str] = set()
    for operation in operations:
        if operation.selected_backend != "hpc":
            continue
        expected = aox_hpc_workspace_id(
            sandbox_workspace_id=str(operation.sandbox_workspace_id or ""),
            hpc_workspace_label=context.roots.hpc_workspace_label,
        )
        if operation.hpc_workspace_id != expected:
            raise LiveProductPathError(
                "hpc_workspace_binding_mismatch",
                "controlled operation does not bind the attempt-authoritative HPC workspace label",
                details={"operation_id": operation.operation_id},
            )
        workspace_ids.add(expected)
    if not workspace_ids:
        raise LiveProductPathError(
            "hpc_workspace_binding_missing",
            "reached AOX attempt has no authoritative HPC workspace identity",
        )
    return workspace_ids


def operation_evidence_record(
    operation: ControlledOperation,
    *,
    scope: Literal["probe", "formal"],
    inputs: list[dict[str, str]],
    outputs: list[dict[str, str]],
    parameters: Mapping[str, object] | None = None,
) -> dict[str, object]:
    material = controlled_operation_identity_material(operation)
    if [item["artifact_id"] for item in inputs] != list(
        operation.input_artifact_ids
    ) or [item["content_digest"] for item in inputs] != list(
        operation.input_artifact_digests
    ):
        raise LiveProductPathError(
            "controlled_operation_input_projection_mismatch",
            "evidence inputs differ from the approval-bound S12 operation",
            details={"operation_id": operation.operation_id},
        )
    result = dict(operation.adapter_result_envelope or {})
    record: dict[str, object] = {
        "operation_id": operation.operation_id,
        "session_id": operation.session_id,
        "task_id": operation.task_id,
        "sandbox_run_id": operation.sandbox_run_id,
        "source_snapshot_artifact_id": operation.source_snapshot_artifact_id,
        "hpc_workspace_id": operation.hpc_workspace_id,
        "canonical_ref_kind": "controlled_operation",
        "kind": f"{operation.sdk_module}.{operation.function_name}",
        "scope": scope,
        "status": operation.status.value,
        "terminal": operation.status.value in _TERMINAL_OPERATION_STATUSES,
        "failure_code": operation.error_code,
        "operation_identity_schema": S12_OPERATION_IDENTITY_SCHEMA,
        "operation_identity_material": material,
        "operation_identity_digest": operation.operation_digest,
        "params_digest": operation.params_digest,
        "source_snapshot_digest": operation.source_snapshot_digest,
        "route_policy_id": operation.route_policy_id,
        "selected_backend": operation.selected_backend,
        "backend_run_id": result.get("provider_request_id")
        or result.get("backend_run_id"),
        "inputs": [dict(item) for item in inputs],
        "outputs": [dict(item) for item in outputs],
    }
    if parameters is not None:
        normalized_parameters = dict(parameters)
        if canonical_digest(normalized_parameters) != operation.params_digest:
            raise LiveProductPathError(
                "controlled_operation_params_digest_mismatch",
                "sealed provider request parameters do not reproduce params_digest",
                details={"operation_id": operation.operation_id},
            )
        record["parameters"] = normalized_parameters
    return record


def _operation_output_artifact_ids(operation: ControlledOperation) -> tuple[str, ...]:
    envelope = dict(operation.adapter_result_envelope or {})
    summary = dict(operation.result_summary or {})
    values: list[str] = []
    for source in (envelope, summary):
        for key in ("output_artifact_ids", "registered_artifact_ids"):
            for value in source.get(key) or []:
                text = str(value)
                if text and text not in values:
                    values.append(text)
    return tuple(values)


def _micu_record_ids(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id FROM live_micu_token_attempts ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise LiveProductPathError(
            "micu_ledger_schema_unavailable",
            "persistent MICU ledger does not expose attempt receipts",
        ) from exc
    finally:
        connection.close()
    return {int(row[0]) for row in rows}


def _new_micu_attempt_receipts(
    path: Path,
    *,
    before_ids: set[int],
) -> tuple[MicuAttemptReceipt, ...]:
    if not path.is_file():
        raise LiveProductPathError(
            "micu_attempt_receipt_missing",
            "positive live execution did not create the persistent MICU ledger",
        )
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, scenario, model, status
            FROM live_micu_token_attempts
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()
    terminal_statuses = {
        "succeeded",
        "succeeded_overage",
        "succeeded_limit_breached",
        "succeeded_estimated",
        "failed_estimated",
    }
    new_rows = [row for row in rows if int(row["id"]) not in before_ids]
    if not new_rows:
        raise LiveProductPathError(
            "micu_attempt_receipt_missing",
            "positive live execution has no newly charged MICU attempt",
        )
    scenarios = {str(row["scenario"] or "") for row in new_rows}
    models = {str(row["model"] or "") for row in new_rows}
    invalid_statuses = sorted(
        str(row["status"] or "")
        for row in new_rows
        if str(row["status"] or "") not in terminal_statuses
    )
    if scenarios != {"aox_blank_world_cutover"} or len(models) != 1 or "" in models:
        raise LiveProductPathError(
            "micu_attempt_attribution_mismatch",
            "new MICU ledger rows are not exclusively bound to the AOX campaign",
            details={"scenarios": sorted(scenarios), "models": sorted(models)},
        )
    if invalid_statuses:
        raise LiveProductPathError(
            "micu_attempt_not_terminal",
            "new MICU attempt rows have not reached a terminal ledger status",
            details={"statuses": invalid_statuses},
        )
    return tuple(
        MicuAttemptReceipt(
            record_id=int(row["id"]),
            scenario=str(row["scenario"]),
            model=str(row["model"]),
        )
        for row in new_rows
    )


def _artifact_bytes(
    context: AttemptRunContext,
    artifact: SessionArtifactRecord,
) -> bytes:
    source = Path(artifact.storage_uri)
    metadata = dict(artifact.metadata or {})
    if source.is_symlink():
        raise LiveProductPathError(
            "catalog_artifact_blob_invalid",
            "cutover evidence rejects symbolic-link catalog artifacts",
            details={"artifact_id": artifact.artifact_id},
        )
    resolved_source = source.resolve()
    resolved_blob_root = context.roots.blob_root.resolve()
    if resolved_blob_root not in resolved_source.parents:
        raise LiveProductPathError(
            "catalog_artifact_blob_unbound",
            "catalog artifact is outside the attempt-scoped immutable blob root",
            details={"artifact_id": artifact.artifact_id},
        )
    if source.is_dir():
        if (
            artifact.kind is not ArtifactKind.CODE
            or metadata.get("semantic_type") != "pipeline_source_snapshot"
            or metadata.get("format") != "source_tree"
        ):
            raise LiveProductPathError(
                "catalog_artifact_blob_invalid",
                "only typed pipeline source snapshots may use directory blobs",
                details={"artifact_id": artifact.artifact_id},
            )
        expected_tree_digest = str(metadata.get("source_tree_digest") or "")
        try:
            return seal_source_tree_envelope(
                source,
                expected_source_tree_digest=expected_tree_digest,
            )
        except CutoverEvidenceError as exc:
            raise LiveProductPathError(
                exc.code,
                "pipeline source snapshot cannot be sealed as self-verifying evidence",
                details={
                    "artifact_id": artifact.artifact_id,
                    **dict(exc.details),
                },
            ) from exc
    if not source.is_file():
        raise LiveProductPathError(
            "catalog_artifact_blob_invalid",
            "cutover evidence requires a regular-file or typed source-tree artifact",
            details={"artifact_id": artifact.artifact_id},
        )
    content = source.read_bytes()
    expected = str(
        metadata.get("content_digest") or metadata.get("sealed_digest") or ""
    )
    actual = _sha256(content)
    if expected != actual:
        raise LiveProductPathError(
            "catalog_artifact_digest_mismatch",
            "catalog artifact bytes differ from their immutable metadata digest",
            details={"artifact_id": artifact.artifact_id},
        )
    return content


def _copy_catalog_artifact(
    context: AttemptRunContext,
    artifact: SessionArtifactRecord,
    *,
    scope: Literal["probe", "formal"],
    origin: str,
    provenance: Mapping[str, object],
    cache: dict[str, CatalogArtifactCopy],
) -> CatalogArtifactCopy:
    metadata = dict(artifact.metadata or {})
    format_value = metadata.get("format")
    artifact_format = format_value if isinstance(format_value, str) else ""
    deliverable_path = (
        artifact.relative_path
        if artifact.relative_path in AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS
        else ""
    )
    declared_deliverable_path = str(dict(provenance).get("deliverable_path") or "")
    declared_contract_id = str(
        dict(provenance).get("deliverable_artifact_contract_id") or ""
    )
    if declared_deliverable_path and declared_deliverable_path != deliverable_path:
        raise LiveProductPathError(
            "final_deliverable_artifact_contract_mismatch",
            "AOX deliverable provenance does not match the catalog relative path",
            details={"artifact_id": artifact.artifact_id},
        )
    if declared_contract_id and (
        not deliverable_path
        or declared_contract_id != AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
    ):
        raise LiveProductPathError(
            "final_deliverable_artifact_contract_mismatch",
            "AOX deliverable provenance declares an unknown artifact contract",
            details={"artifact_id": artifact.artifact_id},
        )
    if deliverable_path:
        expected_kind, expected_format = (
            AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS[deliverable_path]
        )
        if artifact.kind.value != expected_kind or artifact_format != expected_format:
            raise LiveProductPathError(
                "final_deliverable_artifact_contract_mismatch",
                "normalized AOX deliverable has the wrong catalog kind or format",
                details={
                    "path": deliverable_path,
                    "expected_kind": expected_kind,
                    "actual_kind": artifact.kind.value,
                    "expected_format": expected_format,
                    "actual_format": artifact_format,
                },
            )
    existing = cache.get(artifact.artifact_id)
    if existing is not None:
        if (
            existing.record.get("scope") != scope
            or existing.record.get("origin") != origin
        ):
            raise LiveProductPathError(
                "catalog_artifact_owner_ambiguous",
                "one catalog artifact cannot be assigned two canonical evidence owners",
                details={"artifact_id": artifact.artifact_id},
            )
        if deliverable_path:
            existing_path = str(existing.record.get("deliverable_path") or "")
            if existing_path not in {"", deliverable_path}:
                raise LiveProductPathError(
                    "catalog_artifact_owner_ambiguous",
                    "one catalog artifact cannot satisfy two AOX deliverable paths",
                    details={"artifact_id": artifact.artifact_id},
                )
            existing.record.update(
                {
                    "deliverable_path": deliverable_path,
                    "deliverable_artifact_contract_id": (
                        AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
                    ),
                }
            )
            existing_provenance = dict(existing.record.get("provenance") or {})
            existing_provenance.update(
                {
                    "deliverable_path": deliverable_path,
                    "deliverable_artifact_contract_id": (
                        AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
                    ),
                }
            )
            existing.record["provenance"] = existing_provenance
        return existing
    content = _artifact_bytes(context, artifact)
    registration_validation: dict[str, object] | None = None
    if artifact.kind is ArtifactKind.SEQUENCE and content == b"":
        try:
            registration_validation = typed_empty_artifact_validation_receipt(
                kind=artifact.kind.value,
                metadata=dict(artifact.metadata or {}),
            )
        except CutoverEvidenceError as exc:
            raise LiveProductPathError(
                exc.code,
                "zero-record FASTA lacks a reproducible catalog validation receipt",
                details={"artifact_id": artifact.artifact_id},
            ) from exc
    elif dict(artifact.metadata or {}).get("validation_profile") is not None:
        raise LiveProductPathError(
            "typed_empty_artifact_validation_invalid",
            "typed-empty validation profile is attached to a nonempty or non-sequence artifact",
            details={"artifact_id": artifact.artifact_id},
        )
    safe_name = _safe_id(PurePosixPath(artifact.relative_path).name)
    relative_path = f"{scope}/catalog/{_safe_id(artifact.artifact_id)}/{safe_name}"
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    copied = CatalogArtifactCopy(
        record={
            "artifact_id": artifact.artifact_id,
            "relative_path": relative_path,
            "scope": scope,
            "origin": origin,
            "kind": artifact.kind.value,
            **({} if not artifact_format else {"format": artifact_format}),
            **(
                {}
                if not deliverable_path
                else {
                    "deliverable_path": deliverable_path,
                    "deliverable_artifact_contract_id": (
                        AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
                    ),
                }
            ),
            **(
                {}
                if registration_validation is None
                else {"registration_validation": registration_validation}
            ),
            "provenance": {
                **dict(provenance),
                "catalog_artifact_id": artifact.artifact_id,
                "catalog_relative_path": artifact.relative_path,
                **(
                    {}
                    if not deliverable_path
                    else {
                        "deliverable_path": deliverable_path,
                        "deliverable_artifact_contract_id": (
                            AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
                        ),
                    }
                ),
            },
        },
        content=content,
        content_digest=_sha256(content),
    )
    cache[artifact.artifact_id] = copied
    return copied


def _require_artifact(
    artifacts: Mapping[str, SessionArtifactRecord],
    artifact_id: str,
) -> SessionArtifactRecord:
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        raise LiveProductPathError(
            "catalog_artifact_record_missing",
            "operation references an artifact absent from its durable session catalog",
            details={"artifact_id": artifact_id},
        )
    return artifact


def _artifact_ref(copy: CatalogArtifactCopy) -> dict[str, str]:
    return {
        "artifact_id": str(copy.record["artifact_id"]),
        "content_digest": copy.content_digest,
    }


def _declared_operation_input_refs(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
    scope: Literal["probe", "formal"] = "formal",
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for artifact_id, declared_digest in zip(
        operation.input_artifact_ids,
        operation.input_artifact_digests,
        strict=True,
    ):
        artifact = _require_artifact(artifacts, artifact_id)
        copy = _copy_catalog_artifact(
            context,
            artifact,
            scope=scope,
            origin="operation",
            provenance={"operation_input_for": operation.operation_id},
            cache=copies,
        )
        if copy.content_digest != declared_digest:
            raise LiveProductPathError(
                "controlled_operation_input_digest_mismatch",
                "catalog bytes differ from the approval-bound controlled-operation input",
                details={
                    "operation_id": operation.operation_id,
                    "artifact_id": artifact_id,
                },
            )
        refs.append({"artifact_id": artifact_id, "content_digest": declared_digest})
    return refs


def _provider_request_parameters(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
) -> dict[str, object]:
    request_artifacts = [
        artifacts[artifact_id]
        for artifact_id in _operation_output_artifact_ids(operation)
        if artifact_id in artifacts
        and PurePosixPath(artifacts[artifact_id].relative_path).name
        == "provider_request.json"
    ]
    if len(request_artifacts) != 1:
        raise LiveProductPathError(
            "provider_request_artifact_ambiguous",
            "controlled provider operation must have one sealed provider_request.json",
            details={"operation_id": operation.operation_id},
        )
    try:
        payload = json.loads(_artifact_bytes(context, request_artifacts[0]))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveProductPathError(
            "provider_request_artifact_invalid",
            "sealed provider request artifact is not valid JSON",
            details={"operation_id": operation.operation_id},
        ) from exc
    params = payload.get("params") if isinstance(payload, dict) else None
    if (
        not isinstance(params, dict)
        or canonical_digest(params) != operation.params_digest
    ):
        raise LiveProductPathError(
            "provider_request_params_digest_mismatch",
            "sealed provider request parameters do not reproduce the S12 params digest",
            details={"operation_id": operation.operation_id},
        )
    return dict(params)


def _raw_provider_response_digests(content: bytes) -> tuple[str, ...]:
    try:
        payload = _strict_json_object(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return ()
    if (
        not isinstance(payload, dict)
        or payload.get("schema_id") != "provider_raw_http_response_set@1"
        or not isinstance(payload.get("responses"), list)
    ):
        return ()
    digests: list[str] = []
    for raw_record in payload["responses"]:
        if not isinstance(raw_record, dict):
            return ()
        try:
            raw = base64.b64decode(
                str(raw_record.get("body_base64") or ""),
                validate=True,
            )
        except ValueError:
            return ()
        digest = _sha256(raw)
        if (
            raw_record.get("body_encoding") != "base64"
            or raw_record.get("size_bytes") != len(raw)
            or raw_record.get("body_digest") != digest
            or base64.b64encode(raw).decode("ascii")
            != raw_record.get("body_base64")
        ):
            return ()
        if payload.get("provider") == "uniprot":
            try:
                body = _strict_json_object(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return ()
            if not isinstance(body.get("results"), list):
                return ()
        digests.append(digest)
    return tuple(digests)


def _provider_output_copies(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
    scope: Literal["probe", "formal"] = "formal",
) -> tuple[list[CatalogArtifactCopy], str]:
    selected: list[CatalogArtifactCopy] = []
    raw_response_digests: list[str] = []
    for artifact_id in _operation_output_artifact_ids(operation):
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            continue
        name = PurePosixPath(artifact.relative_path).name
        if name in {"provider_request.json", "provider_observation.json"}:
            continue
        copy = _copy_catalog_artifact(
            context,
            artifact,
            scope=scope,
            origin="operation",
            provenance={
                "operation_id": operation.operation_id,
                "provider": operation.function_name,
            },
            cache=copies,
        )
        selected.append(copy)
        raw_response_digests.extend(_raw_provider_response_digests(copy.content))
    if not selected or not raw_response_digests:
        raise LiveProductPathError(
            "provider_response_artifact_missing",
            "provider operation lacks a sealed raw HTTP response receipt",
            details={"operation_id": operation.operation_id},
        )
    return selected, raw_response_digests[-1]


def _tool_output_copies(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
    scope: Literal["probe", "formal"] = "formal",
) -> list[CatalogArtifactCopy]:
    selected = [
        _copy_catalog_artifact(
            context,
            _require_artifact(artifacts, artifact_id),
            scope=scope,
            origin="operation",
            provenance={
                "operation_id": operation.operation_id,
                "tool": operation.function_name,
            },
            cache=copies,
        )
        for artifact_id in _operation_output_artifact_ids(operation)
    ]
    if not selected:
        raise LiveProductPathError(
            "toolchain_output_artifact_missing",
            "completed HPC operation has no sealed declared output",
            details={"operation_id": operation.operation_id},
        )
    return selected


def _approval_record(
    operation: ControlledOperation,
    approvals: Mapping[str, object],
) -> dict[str, object]:
    approval = approvals.get(str(operation.approval_id or ""))
    if (
        approval is None
        or getattr(getattr(approval, "status", None), "value", None) != "approved"
        or getattr(approval, "request_ref", None) != operation.operation_id
    ):
        raise LiveProductPathError(
            "controlled_operation_approval_missing",
            "controlled operation lacks its exact durable approved request",
            details={"operation_id": operation.operation_id},
        )
    return {
        "approval_id": str(operation.approval_id),
        "operation_id": operation.operation_id,
        "operation_identity_digest": operation.operation_digest,
        "decision": "approved",
    }


def _sandbox_calculation_record(
    *,
    run: object,
    role: str,
    calculation_id: str,
    calculation_contract_digest: str,
    calculation_implementation_digest: str,
    parameters: Mapping[str, object],
    inputs: list[dict[str, str]],
    outputs: list[dict[str, str]],
) -> dict[str, object]:
    params = dict(parameters)
    params_digest = canonical_digest(params)
    sandbox_run_id = str(getattr(run, "sandbox_run_id"))
    source_snapshot_artifact_id = str(getattr(run, "source_snapshot_artifact_id") or "")
    source_snapshot_digest = str(getattr(run, "source_tree_digest") or "")
    workspace_id = str(getattr(run, "sandbox_workspace_id") or "")
    if (
        not source_snapshot_artifact_id
        or not source_snapshot_digest
        or not workspace_id
    ):
        raise LiveProductPathError(
            "sandbox_calculation_source_snapshot_missing",
            "sandbox calculation is not bound to its source snapshot",
            details={"sandbox_run_id": sandbox_run_id},
        )
    material = {
        "schema_version": SANDBOX_CALCULATION_IDENTITY_SCHEMA,
        "sandbox_run_id": sandbox_run_id,
        "sandbox_workspace_id": workspace_id,
        "source_snapshot_artifact_id": source_snapshot_artifact_id,
        "source_snapshot_digest": source_snapshot_digest,
        "calculation_id": calculation_id,
        "calculation_contract_digest": calculation_contract_digest,
        "calculation_implementation_digest": calculation_implementation_digest,
        "params_digest": params_digest,
        "input_artifact_ids": [item["artifact_id"] for item in inputs],
        "input_artifact_digests": [item["content_digest"] for item in inputs],
        "output_artifact_ids": [item["artifact_id"] for item in outputs],
        "output_artifact_digests": [item["content_digest"] for item in outputs],
    }
    return {
        "operation_id": f"sandbox_calc_{_safe_id(sandbox_run_id)}_{_safe_id(role)}",
        "canonical_ref_kind": "sandbox_calculation",
        "kind": calculation_id,
        "scope": "formal",
        "status": "completed",
        "terminal": True,
        "failure_code": None,
        "operation_identity_schema": SANDBOX_CALCULATION_IDENTITY_SCHEMA,
        "operation_identity_material": material,
        "operation_identity_digest": sandbox_calculation_digest(material),
        "params_digest": params_digest,
        "parameters": params,
        "source_snapshot_digest": source_snapshot_digest,
        "route_policy_id": "sandbox.calculation:v1",
        "selected_backend": "sandbox_run",
        "backend_run_id": sandbox_run_id,
        "inputs": [dict(item) for item in inputs],
        "outputs": [dict(item) for item in outputs],
    }


def _single_completed_operation(
    operations: tuple[ControlledOperation, ...],
    *,
    sdk_module: str,
    function_name: str,
) -> ControlledOperation:
    matches = [
        operation
        for operation in operations
        if operation.sdk_module == sdk_module
        and operation.function_name == function_name
    ]
    if len(matches) != 1:
        raise LiveProductPathError(
            "formal_operation_receipt_ambiguous",
            "formal product path requires exactly one completed canonical operation",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                **_operation_surface_details(matches),
            },
        )
    if matches[0].status.value != "completed":
        raise LiveProductPathError(
            "formal_required_operation_not_completed",
            "a required scientific operation did not complete",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                "status": matches[0].status.value,
            },
        )
    return matches[0]


def _assert_cutover_operation_budget_before_approval(
    provider: SQLiteRepositoryProvider,
    *,
    session_id: str,
    approval_id: str,
) -> None:
    """Reject an already-ineligible operation history before external execution.

    The cutover evidence contract admits one controlled operation for every
    reached SDK method and does not adopt effects across a failed sandbox run.
    Checking both histories at approval time prevents a replacement or a later
    operation in an already-ineligible source lineage from consuming provider
    or runner resources.
    """

    with provider.read() as scope:
        operations = tuple(
            scope.repositories.controlled_operations.list_by_session(session_id)
        )
        sandbox_runs = tuple(
            scope.repositories.sandbox_runs.list_by_session(session_id)
        )
    approval_matches = [
        operation for operation in operations if operation.approval_id == approval_id
    ]
    if len(approval_matches) != 1:
        raise LiveProductPathError(
            "cutover_approval_operation_binding_invalid",
            "cutover approval must bind exactly one controlled operation",
            details={
                "session_id": session_id,
                "approval_id": approval_id,
                "operation_count": len(approval_matches),
            },
        )
    current = approval_matches[0]
    same_method = [
        operation
        for operation in operations
        if operation.sdk_module == current.sdk_module
        and operation.function_name == current.function_name
    ]
    if len(same_method) != 1:
        raise LiveProductPathError(
            "cutover_operation_budget_exceeded",
            "cutover operation history already contains this reached SDK method",
            details={
                "session_id": session_id,
                "approval_id": approval_id,
                "sdk_method": f"{current.sdk_module}.{current.function_name}",
                "operation_count": len(same_method),
                "operations": [
                    {
                        "operation_id": operation.operation_id,
                        "status": operation.status.value,
                    }
                    for operation in same_method
                ],
            },
        )
    failed_sandbox_runs = [
        run
        for run in sandbox_runs
        if getattr(getattr(run, "status", None), "value", None)
        in (_TERMINAL_SANDBOX_STATUSES - {"completed"})
    ]
    if failed_sandbox_runs:
        raise LiveProductPathError(
            "cutover_sandbox_history_failed",
            "cutover sandbox history already contains a terminal failed run",
            details={
                "session_id": session_id,
                "approval_id": approval_id,
                "sandbox_runs": [
                    {
                        "sandbox_run_id": str(
                            getattr(run, "sandbox_run_id", "") or ""
                        ),
                        "status": str(getattr(run.status, "value", "")),
                        "error_code": getattr(run, "error_code", None),
                    }
                    for run in failed_sandbox_runs
                ],
            },
        )
    if current.sdk_module == "bio" and current.function_name == "hmmer_search":
        with provider.read() as scope:
            sandbox_run = scope.repositories.sandbox_runs.get(current.sandbox_run_id)
        raw_policy = (
            None
            if sandbox_run is None
            else getattr(sandbox_run, "resource_policy", None)
        )
        policy = {} if not isinstance(raw_policy, dict) else dict(raw_policy)
        observed_timeout = policy.get("timeout_seconds")
        observed_policy_version = policy.get("exec_policy_version")
        if (
            type(observed_timeout) is not int
            or observed_timeout != AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
            or observed_policy_version != EXEC_POLICY_VERSION
        ):
            raise LiveProductPathError(
                "cutover_hmmer_sandbox_timeout_invalid",
                "AOX HMMER approval requires the sealed HMM-capable sandbox timeout policy",
                details={
                    "session_id": session_id,
                    "approval_id": approval_id,
                    "operation_id": current.operation_id,
                    "expected_timeout_seconds": (
                        AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
                    ),
                    "observed_timeout_seconds": (
                        observed_timeout if type(observed_timeout) is int else None
                    ),
                    "expected_exec_policy_version": EXEC_POLICY_VERSION,
                    "observed_exec_policy_version": (
                        observed_policy_version
                        if isinstance(observed_policy_version, str)
                        else None
                    ),
                },
            )
    failed = [
        operation
        for operation in operations
        if operation.operation_id != current.operation_id
        and operation.status
        in {
            ControlledOperationStatus.FAILED,
            ControlledOperationStatus.RECOVERY_FAILED,
        }
    ]
    if failed:
        raise LiveProductPathError(
            "cutover_operation_history_failed",
            "cutover operation history already contains a terminal failed operation",
            details={
                "session_id": session_id,
                "approval_id": approval_id,
                "operations": [
                    {
                        "operation_id": operation.operation_id,
                        "sdk_method": (
                            f"{operation.sdk_module}.{operation.function_name}"
                        ),
                        "status": operation.status.value,
                        "error_code": operation.error_code,
                    }
                    for operation in failed
                ],
            },
        )


def _optional_completed_operation(
    operations: tuple[ControlledOperation, ...],
    *,
    sdk_module: str,
    function_name: str,
) -> ControlledOperation | None:
    matches = [
        operation
        for operation in operations
        if operation.sdk_module == sdk_module
        and operation.function_name == function_name
    ]
    if len(matches) > 1:
        raise LiveProductPathError(
            "formal_operation_receipt_ambiguous",
            "formal product path has more than one canonical operation for an optional role",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                **_operation_surface_details(matches),
            },
        )
    if matches and matches[0].status.value != "completed":
        raise LiveProductPathError(
            "formal_optional_operation_not_completed",
            "an attempted optional scientific operation did not complete and cannot be hidden by an empty branch",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                "status": matches[0].status.value,
            },
        )
    return None if not matches else matches[0]


def _operation_surface_details(
    operations: list[ControlledOperation],
) -> dict[str, object]:
    status_histogram: dict[str, int] = {}
    for operation in operations:
        status = operation.status.value
        status_histogram[status] = status_histogram.get(status, 0) + 1
    return {
        "operation_count": len(operations),
        "completed_count": status_histogram.get("completed", 0),
        "failed_count": (
            status_histogram.get("failed", 0)
            + status_histogram.get("recovery_failed", 0)
        ),
        "nonterminal_count": sum(
            count
            for status, count in status_histogram.items()
            if status not in {"completed", "failed", "recovery_failed"}
        ),
        "status_histogram": {
            status: status_histogram[status] for status in sorted(status_histogram)
        },
        "operation_ids": sorted(operation.operation_id for operation in operations),
    }


def _copy_with_name(
    copies: list[CatalogArtifactCopy],
    *,
    names: set[str],
    identity: str,
) -> CatalogArtifactCopy:
    matches = [
        copy
        for copy in copies
        if PurePosixPath(str(copy.record["relative_path"])).name in names
        or PurePosixPath(
            str(
                dict(copy.record.get("provenance") or {}).get("catalog_relative_path")
                or ""
            )
        ).name
        in names
    ]
    if len(matches) != 1:
        raise LiveProductPathError(
            "formal_artifact_role_ambiguous",
            "formal operation output does not resolve to one required artifact role",
            details={"identity": identity, "matching_count": len(matches)},
        )
    return matches[0]


def _final_deliverable_copies(
    context: AttemptRunContext,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
) -> tuple[
    dict[str, CatalogArtifactCopy],
    dict[str, SessionArtifactRecord],
    dict[str, object],
]:
    by_path: dict[str, list[SessionArtifactRecord]] = {
        path: [] for path in S15_AOX_HMM_FIXED_DELIVERABLES
    }
    for artifact in artifacts.values():
        if artifact.relative_path in by_path:
            by_path[artifact.relative_path].append(artifact)
    ambiguous = {
        path: len(records) for path, records in by_path.items() if len(records) != 1
    }
    if ambiguous:
        raise LiveProductPathError(
            "final_deliverable_catalog_ambiguous",
            "every normalized AOX deliverable must resolve to exactly one catalog artifact",
            details={"path_counts": ambiguous},
        )
    artifact_by_path = {path: records[0] for path, records in by_path.items()}
    text_by_path: dict[str, str] = {}
    metadata_by_path: dict[str, dict[str, object]] = {}
    copy_by_path: dict[str, CatalogArtifactCopy] = {}
    for path, artifact in artifact_by_path.items():
        expected_kind, expected_format = (
            AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS[path]
        )
        raw_format = dict(artifact.metadata or {}).get("format")
        actual_format = raw_format if isinstance(raw_format, str) else ""
        if artifact.kind.value != expected_kind or actual_format != expected_format:
            raise LiveProductPathError(
                "final_deliverable_artifact_contract_mismatch",
                "normalized AOX deliverable has the wrong catalog kind or format",
                details={
                    "path": path,
                    "expected_kind": expected_kind,
                    "actual_kind": artifact.kind.value,
                    "expected_format": expected_format,
                    "actual_format": actual_format,
                },
            )
        copied = _copy_catalog_artifact(
            context,
            artifact,
            scope="formal",
            origin="operation",
            provenance={
                "calculation_id": AOX_DELIVERABLE_NORMALIZATION_ID,
                "deliverable_path": path,
                "deliverable_artifact_contract_id": (
                    AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
                ),
            },
            cache=copies,
        )
        try:
            text_by_path[path] = copied.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LiveProductPathError(
                "final_deliverable_not_utf8",
                "normalized AOX deliverables must be UTF-8 scientific artifacts",
                details={"path": path},
            ) from exc
        metadata_by_path[path] = dict(artifact.metadata or {})
        copy_by_path[path] = copied
    validation = _s15_aox_validate_final_artifacts(
        set(copy_by_path),
        text_by_path,
        metadata_by_path,
    )
    if validation.get("passed") is not True:
        raise LiveProductPathError(
            "final_deliverable_validation_failed",
            "normalized AOX deliverables failed the independent S15 validator",
            details={
                "error_count": len(validation.get("errors") or []),
                "missing_count": len(validation.get("missing_paths") or []),
            },
        )
    return copy_by_path, artifact_by_path, validation


def _sandbox_run_for_final_deliverables(
    final_artifacts: Mapping[str, SessionArtifactRecord],
    sandbox_runs: tuple[object, ...],
) -> object:
    provenance_identities = {
        (
            str(dict(artifact.metadata or {}).get("sandbox_workspace_id") or ""),
            str(dict(artifact.metadata or {}).get("source_snapshot_artifact_id") or ""),
            str(dict(artifact.metadata or {}).get("source_tree_digest") or ""),
        )
        for artifact in final_artifacts.values()
    }
    if len(provenance_identities) != 1:
        raise LiveProductPathError(
            "final_deliverable_run_identity_ambiguous",
            "normalized deliverables do not share one sandbox source identity",
            details={"identity_count": len(provenance_identities)},
        )
    workspace_id, source_artifact_id, source_digest = next(iter(provenance_identities))
    if not workspace_id or not source_artifact_id or not source_digest:
        raise LiveProductPathError(
            "final_deliverable_run_identity_missing",
            "normalized deliverables lack their sandbox source identity",
        )
    candidates = [
        run
        for run in sandbox_runs
        if str(getattr(run, "sandbox_workspace_id", "")) == workspace_id
        and str(getattr(run, "source_snapshot_artifact_id", "")) == source_artifact_id
        and str(getattr(run, "source_tree_digest", "")) == source_digest
        and getattr(getattr(run, "status", None), "value", None) == "completed"
    ]
    if len(candidates) > 1:
        artifact_times = [artifact.created_at for artifact in final_artifacts.values()]
        bounded = [
            run
            for run in candidates
            if str(getattr(run, "started_at", "") or getattr(run, "created_at", ""))
            <= min(artifact_times)
            and str(getattr(run, "ended_at", "") or getattr(run, "updated_at", ""))
            >= max(artifact_times)
        ]
        candidates = bounded
    if len(candidates) != 1:
        raise LiveProductPathError(
            "final_deliverable_run_receipt_ambiguous",
            "normalized deliverables do not resolve to one completed sandbox run",
            details={"matching_run_count": len(candidates)},
        )
    return candidates[0]


def _score_filtered_hmmer_accessions(
    parsed_hits_content: bytes,
    score_filtered_content: bytes,
) -> aox_hmmer.ScoreFilteredAccessionsResult:
    try:
        result = aox_hmmer.parse_and_filter_csv(parsed_hits_content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise LiveProductPathError(
            "hmmer_score_filter_invalid",
            "EBI HMMER parsed hits do not satisfy hmmer_score_filtered_accessions@1",
        ) from exc
    expected = result.to_csv().encode("utf-8")
    if score_filtered_content != expected:
        raise LiveProductPathError(
            "hmmer_score_filter_output_mismatch",
            "registered pre-UniProt accession artifact differs from offline recomputation",
            details={
                "expected_digest": _sha256(expected),
                "actual_digest": _sha256(score_filtered_content),
            },
        )
    return result


def _sandbox_source_implementation_digest(run: object, calculation_id: str) -> str:
    return canonical_digest(
        {
            "calculation_id": calculation_id,
            "source_snapshot_artifact_id": str(
                getattr(run, "source_snapshot_artifact_id") or ""
            ),
            "source_snapshot_digest": str(getattr(run, "source_tree_digest") or ""),
        }
    )


def _operation_backend_run_id(operation_record: Mapping[str, object]) -> str:
    backend_run_id = str(operation_record.get("backend_run_id") or "")
    if not backend_run_id:
        raise LiveProductPathError(
            "controlled_operation_backend_receipt_missing",
            "completed controlled operation lacks its canonical backend run identity",
            details={"operation_id": operation_record.get("operation_id")},
        )
    return backend_run_id


def _controlled_provider_receipt(
    *,
    provider_name: str,
    operation: ControlledOperation,
    operation_record: Mapping[str, object],
    output_copies: list[CatalogArtifactCopy],
    response_digest: str,
) -> dict[str, object]:
    invocation_id = _operation_backend_run_id(operation_record)
    return {
        "provider_record_id": f"provider_record_{provider_name}_{_safe_id(operation.operation_id)}",
        "provider": provider_name,
        "status": "completed",
        "canonical_ref_kind": "controlled_operation",
        "invocation_id": invocation_id,
        "operation_id": operation.operation_id,
        "cache_hit": False,
        "request_digest": operation.params_digest,
        "response_digest": response_digest,
        "artifact_ids": [str(copy.record["artifact_id"]) for copy in output_copies],
        "source_ref_ids": [],
    }


def _upstream_empty_provider_receipt(
    context: AttemptRunContext,
    *,
    upstream_provider_record: Mapping[str, object],
    derivation_operation: Mapping[str, object],
    derived_accession_artifact: CatalogArtifactCopy,
    reason: str,
) -> tuple[dict[str, object], dict[str, object]]:
    provider_record_id = (
        f"provider_record_uniprot_upstream_empty_{_safe_id(context.roots.attempt_id)}"
    )
    artifact_id = f"art_uniprot_upstream_empty_{_safe_id(context.roots.attempt_id)}"
    derived_accessions_digest = canonical_digest([])
    decision_material = {
        "reason": reason,
        "upstream_provider_record_id": str(
            upstream_provider_record.get("provider_record_id") or ""
        ),
        "derivation_operation_id": str(derivation_operation.get("operation_id") or ""),
        "derived_accession_artifact_id": str(
            derived_accession_artifact.record["artifact_id"]
        ),
        "derived_accession_artifact_digest": (
            derived_accession_artifact.content_digest
        ),
        "derived_accessions_digest": derived_accessions_digest,
    }
    receipt_payload: dict[str, object] = {
        "schema_id": "provider_upstream_empty_receipt@1",
        "provider_record_id": provider_record_id,
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "operation_id": None,
        "invocation_id": None,
        "provider_io_performed": False,
        "cache_consulted": False,
        **decision_material,
        "decision_input_digest": canonical_digest(decision_material),
    }
    receipt_payload["skip_receipt_digest"] = canonical_digest(receipt_payload)
    content = canonical_json_bytes(receipt_payload) + b"\n"
    relative_path = "formal/provider/uniprot-upstream-empty.json"
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    artifact_record = {
        "artifact_id": artifact_id,
        "relative_path": relative_path,
        "scope": "formal",
        "origin": "attestation",
        "kind": "provider_receipt",
        "provenance": {
            "provider_record_id": provider_record_id,
            "upstream_provider_record_id": decision_material[
                "upstream_provider_record_id"
            ],
            "derivation_operation_id": decision_material["derivation_operation_id"],
            "skip_receipt_digest": receipt_payload["skip_receipt_digest"],
        },
    }
    provider_record = {
        "provider_record_id": provider_record_id,
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "invocation_id": None,
        "operation_id": None,
        "cache_hit": False,
        "request_digest": None,
        "response_digest": None,
        "artifact_ids": [artifact_id],
        "source_ref_ids": [],
        "reason": reason,
        "skip_receipt_digest": receipt_payload["skip_receipt_digest"],
        "provider_io_performed": False,
        "cache_consulted": False,
    }
    return provider_record, artifact_record


def _toolchain_receipt(
    *,
    tool_name: str,
    operation: ControlledOperation,
    operation_record: Mapping[str, object],
) -> dict[str, object]:
    expected = AOX_TOOLCHAIN_RUNTIME_CONTRACTS.get(tool_name)
    runtime_identity = dict(
        dict(operation.result_summary or {}).get("toolchain_runtime_identity") or {}
    )
    required_identity = {
        "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": None if expected is None else expected["tool_id"],
        "adapter_id": None if expected is None else expected["adapter_id"],
        "command_template_id": (
            None if expected is None else expected["command_template_id"]
        ),
    }
    identity_keys = set(required_identity) | {"runner_contract_digest", "image_digest"}
    if (
        expected is None
        or str(operation.toolchain_id or "") != expected["toolchain_id"]
        or set(runtime_identity) != identity_keys
        or any(
            runtime_identity.get(key) != value
            for key, value in required_identity.items()
        )
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(runtime_identity.get("runner_contract_digest") or ""),
        )
        is None
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(runtime_identity.get("image_digest") or ""),
        )
        is None
    ):
        raise LiveProductPathError(
            "toolchain_image_identity_missing",
            "HPC operation lacks its runner-attested same-shell SIF identity",
            details={"operation_id": operation.operation_id},
        )
    return {
        "toolchain_record_id": f"toolchain_record_{_safe_id(operation.operation_id)}",
        "toolchain_id": expected["toolchain_id"],
        "tool": tool_name,
        "operation_id": operation.operation_id,
        "job_id": _operation_backend_run_id(operation_record),
        "runtime_identity_schema": runtime_identity["schema_id"],
        "attestation_scope": runtime_identity["attestation_scope"],
        "execution_mode": runtime_identity["execution_mode"],
        "tool_id": runtime_identity["tool_id"],
        "adapter_id": runtime_identity["adapter_id"],
        "command_template_id": runtime_identity["command_template_id"],
        "runner_contract_digest": runtime_identity["runner_contract_digest"],
        "image_digest": runtime_identity["image_digest"],
        "status": "completed",
    }


def _pubmed_receipts(
    context: AttemptRunContext,
    *,
    sources: tuple[object, ...],
    invocation: object,
    input_document: object,
    output_document: object,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
) -> tuple[dict[str, object], dict[str, object], CatalogArtifactCopy]:
    invocation_id = str(getattr(invocation, "invocation_id"))
    source_rows = [
        source for source in sources if getattr(source, "provider", None) == "pubmed"
    ]
    if not source_rows or any(
        not str(getattr(source, "pmid", "") or "").isdigit()
        or getattr(source, "invocation_id", None) != invocation_id
        for source in source_rows
    ):
        raise LiveProductPathError(
            "pubmed_source_receipt_invalid",
            "PubMed source rows must bind numeric PMIDs to one research invocation",
        )
    request_digests = {
        str(getattr(source, "request_digest", "") or "") for source in source_rows
    }
    response_digests = {
        str(getattr(source, "response_digest", "") or "") for source in source_rows
    }
    evidence_ids = {
        str(getattr(source, "evidence_artifact_id", "") or "") for source in source_rows
    }
    cache_statuses = {
        str(
            dict(getattr(source, "provider_provenance", None) or {}).get("cache_status")
            or ""
        )
        for source in source_rows
    }
    if (
        len(request_digests) != 1
        or "" in request_digests
        or len(response_digests) != 1
        or "" in response_digests
        or len(evidence_ids) != 1
        or "" in evidence_ids
        or not cache_statuses.issubset({"", "disabled", "bypass", "miss"})
    ):
        raise LiveProductPathError(
            "pubmed_provider_provenance_ambiguous",
            "PubMed source rows do not share one cache-bypassed provider receipt",
        )
    evidence_artifact = _require_artifact(artifacts, next(iter(evidence_ids)))
    invocation_task_id = getattr(invocation, "task_id", None)
    invocation_lane_id = getattr(invocation, "lane_id", None)
    if (
        evidence_artifact.invocation_id != invocation_id
        or evidence_artifact.task_id != invocation_task_id
        or evidence_artifact.lane_id != invocation_lane_id
        or any(
            getattr(source, "task_id", None) != invocation_task_id
            or getattr(source, "lane_id", None) != invocation_lane_id
            for source in source_rows
        )
    ):
        raise LiveProductPathError(
            "pubmed_primary_lineage_mismatch",
            "PubMed task, invocation, artifact, and source lineage is inconsistent",
        )
    evidence_copy = _copy_catalog_artifact(
        context,
        evidence_artifact,
        scope="formal",
        origin="engine_invocation",
        provenance={
            "invocation_id": invocation_id,
            "engine_name": "research_tool",
            "provider": "pubmed",
            "task_id": invocation_task_id,
            "lane_id": invocation_lane_id,
        },
        cache=copies,
    )
    input_ref = str(getattr(invocation, "input_ref", "") or "")
    output_ref = str(getattr(invocation, "output_ref", "") or "")
    if (
        getattr(invocation, "engine_name", None) != "research_tool"
        or getattr(getattr(invocation, "status", None), "value", None) != "succeeded"
        or not input_ref
        or not output_ref
        or getattr(input_document, "document_id", None) != input_ref
        or getattr(output_document, "document_id", None) != output_ref
    ):
        raise LiveProductPathError(
            "pubmed_engine_invocation_invalid",
            "PubMed evidence does not close through its terminal research invocation",
        )
    source_refs = [
        {
            "source_ref_id": str(getattr(source, "source_ref_id")),
            "pmid": str(getattr(source, "pmid")),
            "title": str(getattr(source, "title", "") or ""),
            "locator": str(getattr(source, "locator", "") or ""),
            "doi": getattr(source, "doi", None),
            "task_id": getattr(source, "task_id", None),
            "lane_id": getattr(source, "lane_id", None),
            "invocation_id": str(getattr(source, "invocation_id")),
            "evidence_artifact_id": str(
                getattr(source, "evidence_artifact_id")
            ),
        }
        for source in source_rows
    ]
    provider_record = {
        "provider_record_id": f"provider_record_pubmed_{_safe_id(invocation_id)}",
        "provider": "pubmed",
        "status": "completed",
        "canonical_ref_kind": "engine_invocation",
        "invocation_id": invocation_id,
        "operation_id": None,
        "cache_hit": False,
        "request_digest": next(iter(request_digests)),
        "response_digest": next(iter(response_digests)),
        "artifact_ids": [str(evidence_copy.record["artifact_id"])],
        "source_ref_ids": [row["source_ref_id"] for row in source_refs],
        "source_refs": source_refs,
    }
    invocation_record = {
        "invocation_id": invocation_id,
        "engine_name": "research_tool",
        "status": "succeeded",
        "task_id": str(invocation_task_id or ""),
        "lane_id": (
            None if invocation_lane_id is None else str(invocation_lane_id)
        ),
        "input_ref": input_ref,
        "input_document_digest": canonical_digest(getattr(input_document, "payload")),
        "output_ref": output_ref,
        "output_document_digest": canonical_digest(getattr(output_document, "payload")),
        "started_at": str(getattr(invocation, "started_at") or ""),
        "finished_at": str(getattr(invocation, "finished_at") or ""),
        "artifact_refs": [_artifact_ref(evidence_copy)],
    }
    if not invocation_record["task_id"]:
        raise LiveProductPathError(
            "pubmed_engine_invocation_scope_missing",
            "PubMed research invocation is not bound to its delegated task",
        )
    return provider_record, invocation_record, evidence_copy


def _task_receipts(
    *,
    tasks: tuple[object, ...],
    agents: tuple[object, ...],
    documents: tuple[object, ...],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    required_roles = {"researcher", "executor", "reporter"}
    agents_by_id = {
        str(getattr(agent, "agent_id")): agent
        for agent in agents
        if str(getattr(agent, "role", "")) in required_roles
    }
    finish_documents: dict[str, list[object]] = {}
    for document in documents:
        if getattr(document, "document_kind", None) != "task_finish":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        task_id = str(payload.get("task_id") or "")
        if task_id:
            finish_documents.setdefault(task_id, []).append(document)
    receipts: list[dict[str, object]] = []
    role_ids: dict[str, str] = {}
    for task in tasks:
        assigned_ref = str(getattr(task, "assigned_ref", "") or "")
        agent = agents_by_id.get(assigned_ref)
        if agent is None:
            raise LiveProductPathError(
                "formal_task_assignment_invalid",
                "formal product task is not assigned to a required canonical teammate",
                details={"task_id": getattr(task, "task_id", None)},
            )
        role = str(getattr(agent, "role"))
        task_id = str(getattr(task, "task_id"))
        if role in role_ids:
            raise LiveProductPathError(
                "formal_task_role_ambiguous",
                "formal product path has more than one task for a required role",
                details={"role": role},
            )
        finish_matches = finish_documents.get(task_id, [])
        if (
            getattr(getattr(task, "status", None), "value", None) != "completed"
            or len(finish_matches) != 1
        ):
            raise LiveProductPathError(
                "formal_task_finish_missing",
                "required teammate task lacks one explicit completed task.finish receipt",
                details={"task_id": task_id},
            )
        finish = finish_matches[0]
        payload = dict(getattr(finish, "payload", None) or {})
        if (
            payload.get("status") != "completed"
            or not str(payload.get("finished_by") or "").strip()
        ):
            raise LiveProductPathError(
                "formal_task_finish_invalid",
                "task.finish payload does not attest the completed business exit",
                details={"task_id": task_id},
            )
        role_ids[role] = task_id
        receipts.append(
            {
                "task_id": task_id,
                "role": role,
                "kind": str(getattr(task, "kind", "")),
                "status": "completed",
                "business_exit": "agent_explicit",
                "assigned_ref": assigned_ref,
                "lane_id": getattr(task, "lane_id", None),
                "finish_ref": str(getattr(finish, "document_id")),
                "finish_payload_digest": canonical_digest(payload),
                "finished_by": str(payload["finished_by"]),
                "evidence_refs": [
                    str(item) for item in payload.get("evidence_refs") or []
                ],
            }
        )
    if set(role_ids) != required_roles:
        raise LiveProductPathError(
            "formal_task_chain_missing",
            "formal product path lacks one researcher, executor, and reporter task",
            details={"observed_roles": sorted(role_ids)},
        )
    return sorted(receipts, key=lambda item: str(item["task_id"])), role_ids


def _select_primary_pubmed_evidence(
    *,
    sources: tuple[object, ...],
    invocations: Mapping[str, object],
    artifacts: Mapping[str, SessionArtifactRecord],
    task_receipts: list[dict[str, object]],
    task_ids_by_role: Mapping[str, str],
) -> PrimaryPubmedEvidence:
    """Select the one PubMed artifact explicitly adopted by the researcher.

    Iterative provider calls remain part of durable control-plane history.  The
    cutover receipt is selected only through the researcher's structured
    ``task.finish.evidence_refs``; timestamps, result counts, and prose are never
    selection authorities.
    """

    researcher_task_id = str(task_ids_by_role.get("researcher") or "")
    researcher_tasks = [
        receipt
        for receipt in task_receipts
        if receipt.get("role") == "researcher"
        and receipt.get("task_id") == researcher_task_id
    ]
    if len(researcher_tasks) != 1:
        raise LiveProductPathError(
            "pubmed_primary_receipt_missing",
            "canonical researcher task receipt is unavailable for PubMed adoption",
        )
    researcher_task = researcher_tasks[0]
    adopted_artifacts: list[SessionArtifactRecord] = []
    for evidence_ref in researcher_task.get("evidence_refs") or []:
        ref = str(evidence_ref)
        if not ref.startswith("artifact:"):
            continue
        artifact = artifacts.get(ref.removeprefix("artifact:"))
        if artifact is None:
            continue
        metadata = dict(artifact.metadata or {})
        if metadata.get("provider") == "pubmed":
            adopted_artifacts.append(artifact)
    if not adopted_artifacts:
        raise LiveProductPathError(
            "pubmed_primary_receipt_missing",
            "researcher task.finish did not adopt a PubMed evidence artifact",
        )
    if len(adopted_artifacts) != 1:
        raise LiveProductPathError(
            "pubmed_primary_receipt_ambiguous",
            "researcher task.finish adopted more than one PubMed evidence artifact",
            details={"adopted_count": len(adopted_artifacts)},
        )

    artifact = adopted_artifacts[0]
    metadata = dict(artifact.metadata or {})
    if (
        metadata.get("schema_version") != "provider_literature_evidence@1"
        or metadata.get("provider_outcome") != "completed"
        or metadata.get("cutover_eligible") is not True
        or artifact.task_id != researcher_task_id
        or artifact.lane_id != researcher_task.get("lane_id")
        or not artifact.invocation_id
    ):
        raise LiveProductPathError(
            "pubmed_primary_receipt_invalid",
            "adopted PubMed artifact is not a cutover-eligible researcher receipt",
            details={"artifact_id": artifact.artifact_id},
        )

    invocation = invocations.get(str(artifact.invocation_id))
    if (
        invocation is None
        or getattr(invocation, "engine_name", None) != "research_tool"
        or getattr(getattr(invocation, "status", None), "value", None)
        != "succeeded"
        or getattr(invocation, "task_id", None) != researcher_task_id
        or getattr(invocation, "lane_id", None) != researcher_task.get("lane_id")
        or not getattr(invocation, "input_ref", None)
        or not getattr(invocation, "output_ref", None)
    ):
        raise LiveProductPathError(
            "pubmed_primary_lineage_mismatch",
            "adopted PubMed artifact does not close through its researcher invocation",
            details={"artifact_id": artifact.artifact_id},
        )

    selected_sources = tuple(
        source
        for source in sources
        if getattr(source, "provider", None) == "pubmed"
        and getattr(source, "evidence_artifact_id", None) == artifact.artifact_id
    )
    if not selected_sources or any(
        not str(getattr(source, "pmid", "") or "").isdigit()
        or getattr(source, "invocation_id", None) != artifact.invocation_id
        or getattr(source, "task_id", None) != researcher_task_id
        or getattr(source, "lane_id", None) != researcher_task.get("lane_id")
        for source in selected_sources
    ):
        raise LiveProductPathError(
            "pubmed_primary_lineage_mismatch",
            "adopted PubMed artifact lacks numeric PMID sources with exact lineage",
            details={"artifact_id": artifact.artifact_id},
        )
    return PrimaryPubmedEvidence(
        sources=selected_sources,
        invocation=invocation,
        artifact=artifact,
        researcher_task=researcher_task,
    )


def _bind_delegation_workflow_receipts(
    context: AttemptRunContext,
    *,
    task_receipts: list[dict[str, object]],
    documents: tuple[object, ...],
) -> list[dict[str, object]]:
    workflow_ref = str(context.identity.get("workflow_ref") or "")
    try:
        expected_manifest = (
            default_workflow_registry().resolve(workflow_ref).manifest.to_dict()
        )
    except ValueError as exc:
        raise LiveProductPathError(
            "formal_workflow_binding_invalid",
            "formal workflow identity does not resolve to the pinned local manifest",
        ) from exc
    required_roles = {"researcher", "executor", "reporter"}
    expected_task_ids = {
        str(receipt.get("task_id") or "")
        for receipt in task_receipts
        if str(receipt.get("role") or "") in required_roles
    }
    delegation_documents: list[object] = []
    for document in documents:
        if getattr(document, "document_kind", None) != "delegation_request":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        if (
            str(payload.get("task_id") or "") in expected_task_ids
            or str(payload.get("role") or "") in required_roles
        ):
            delegation_documents.append(document)
    if len(delegation_documents) != len(required_roles):
        raise LiveProductPathError(
            "formal_delegation_workflow_binding_missing",
            "formal tasks require exactly one durable delegation request each",
            details={"observed_count": len(delegation_documents)},
        )

    bound: list[dict[str, object]] = []
    for receipt in task_receipts:
        task_id = str(receipt.get("task_id") or "")
        role = str(receipt.get("role") or "")
        matches = [
            document
            for document in delegation_documents
            if str(
                dict(getattr(document, "payload", None) or {}).get("task_id") or ""
            )
            == task_id
        ]
        if len(matches) != 1:
            raise LiveProductPathError(
                "formal_delegation_workflow_binding_ambiguous",
                "formal task does not resolve to exactly one durable delegation request",
                details={"task_id": task_id, "match_count": len(matches)},
            )
        document = matches[0]
        payload = dict(getattr(document, "payload", None) or {})
        document_id = str(getattr(document, "document_id", "") or "")
        try:
            request_projection = project_formal_delegation_request(
                payload,
                document_id=document_id,
            )
        except CutoverEvidenceError as exc:
            raise LiveProductPathError(
                "formal_delegation_workflow_binding_invalid",
                "formal delegation request does not match the closed durable schema",
                details={"task_id": task_id, "role": role},
            ) from exc
        workflow_refs = payload.get("workflow_refs")
        workflow_manifests = payload.get("workflow_manifests")
        expected_refs = [workflow_ref] if role == "executor" else []
        expected_manifests = [expected_manifest] if role == "executor" else []
        if (
            payload.get("task_id") != task_id
            or payload.get("role") != role
            or payload.get("agent_id") != receipt.get("assigned_ref")
            or workflow_refs != expected_refs
            or workflow_manifests != expected_manifests
        ):
            raise LiveProductPathError(
                "formal_delegation_workflow_binding_invalid",
                "formal workflow binding must be exact and executor-scoped",
                details={"task_id": task_id, "role": role},
            )
        bound.append(
            {
                **receipt,
                "delegation_request_ref": document_id,
                "delegation_request_digest": canonical_digest(request_projection),
                "delegation_request": request_projection,
                "workflow_refs": list(expected_refs),
                "workflow_manifests": list(expected_manifests),
            }
        )
    return sorted(bound, key=lambda item: str(item["task_id"]))


def _durable_events_by_session(
    repositories: object, session_id: str
) -> tuple[object, ...]:
    events: list[object] = []
    after_cursor = 0
    while True:
        batch = repositories.durable_events.list_by_session(
            session_id,
            after_cursor=after_cursor,
            limit=1_000,
        )
        if not batch:
            break
        events.extend(batch)
        last_cursor = getattr(batch[-1], "cursor", None)
        if not isinstance(last_cursor, int) or last_cursor <= after_cursor:
            raise LiveProductPathError(
                "durable_event_cursor_invalid",
                "durable report event stream did not advance monotonically",
            )
        after_cursor = last_cursor
        if len(batch) < 1_000:
            break
    return tuple(events)


def _durable_browser_approval_events(
    durable_events: tuple[object, ...],
    *,
    browser_receipt: Mapping[str, object] | None,
    session_id: str,
) -> list[dict[str, object]]:
    if browser_receipt is None:
        return []
    receipt = dict(browser_receipt)
    expected = (
        (
            "resolution_event_id",
            "resolution_event_record",
            "approval.resolved",
        ),
        (
            "continuation_event_id",
            "continuation_event_record",
            "sdk_controlled_operation.approval_resolved",
        ),
    )
    records: list[dict[str, object]] = []
    for event_id_key, record_key, event_type in expected:
        event_id = str(receipt.get(event_id_key) or "")
        matches = [
            event
            for event in durable_events
            if str(getattr(event, "event_id", "") or "") == event_id
        ]
        if len(matches) != 1:
            raise LiveProductPathError(
                "browser_approval_durable_event_missing",
                "Chrome receipt does not resolve to one durable approval event",
                details={"event_id": event_id},
            )
        record = _closed_browser_durable_event(
            dict(getattr(matches[0], "to_dict")()),
            expected_type=event_type,  # type: ignore[arg-type]
        )
        if (
            record.get("session_id") != session_id
            or record != receipt.get(record_key)
        ):
            raise LiveProductPathError(
                "browser_approval_durable_event_drift",
                "observed browser event differs from the authoritative durable record",
                details={"event_id": event_id},
            )
        records.append(record)
    if not int(records[0]["cursor"]) < int(records[1]["cursor"]):
        raise LiveProductPathError(
            "browser_approval_durable_event_order_invalid",
            "approval resolution must precede controlled-operation continuation",
        )
    return records


def _report_publish_event_sequence(
    events: tuple[object, ...],
    *,
    report: object,
    draft: object,
) -> list[dict[str, object]]:
    ordered = sorted(events, key=lambda event: int(getattr(event, "cursor") or 0))
    report_payload = getattr(report, "to_dict")()
    draft_payload = getattr(draft, "to_dict")()
    sequences: list[list[object]] = []
    for index, event in enumerate(ordered):
        payload = dict(getattr(event, "payload", None) or {})
        if (
            getattr(event, "event_type", None) != "tool.invoked"
            or payload.get("tool_name") != "report.publish"
            or payload.get("role") != "reporter"
            or not str(payload.get("call_id") or "")
        ):
            continue
        call_id = str(payload["call_id"])
        draft_event = next(
            (
                candidate
                for candidate in ordered[index + 1 :]
                if getattr(candidate, "event_type", None) == "report_draft.updated"
                and dict(getattr(candidate, "payload", None) or {}) == draft_payload
            ),
            None,
        )
        if draft_event is None:
            continue
        draft_index = ordered.index(draft_event)
        report_event = next(
            (
                candidate
                for candidate in ordered[draft_index + 1 :]
                if getattr(candidate, "event_type", None) == "report.generated"
                and dict(getattr(candidate, "payload", None) or {}) == report_payload
            ),
            None,
        )
        if report_event is None:
            continue
        report_index = ordered.index(report_event)
        completed_event = next(
            (
                candidate
                for candidate in ordered[report_index + 1 :]
                if getattr(candidate, "event_type", None) == "tool.completed"
                and dict(getattr(candidate, "payload", None) or {}).get("call_id")
                == call_id
                and dict(getattr(candidate, "payload", None) or {}).get("tool_name")
                == "report.publish"
                and dict(getattr(candidate, "payload", None) or {}).get("role")
                == "reporter"
                and dict(getattr(candidate, "payload", None) or {}).get("ok") is True
            ),
            None,
        )
        if completed_event is not None:
            sequences.append([event, draft_event, report_event, completed_event])
    if len(sequences) != 1:
        raise LiveProductPathError(
            "report_publish_event_receipt_ambiguous",
            "ready report does not resolve to one successful reporter publish sequence",
            details={"matching_sequence_count": len(sequences)},
        )
    return [dict(event.to_dict()) for event in sequences[0]]


def _published_report_receipt(
    context: AttemptRunContext,
    *,
    reports: tuple[object, ...],
    drafts: tuple[object, ...],
    documents: tuple[object, ...],
    durable_events: tuple[object, ...],
    pubmed_provider: Mapping[str, object],
    scientific_artifacts: list[CatalogArtifactCopy],
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    ready_reports = [
        report
        for report in reports
        if getattr(getattr(report, "status", None), "value", None) == "ready"
    ]
    published_drafts = [
        draft
        for draft in drafts
        if getattr(getattr(draft, "status", None), "value", None) == "published"
    ]
    if len(ready_reports) != 1 or len(published_drafts) != 1:
        raise LiveProductPathError(
            "published_report_receipt_ambiguous",
            "formal product path requires exactly one ready report and published draft",
        )
    report = ready_reports[0]
    draft = published_drafts[0]
    if (
        getattr(draft, "published_report_id", None)
        != getattr(report, "report_id", None)
        or not getattr(draft, "content_ref", None)
        or getattr(report, "artifact_id", None) is not None
        or getattr(report, "invocation_id", None) is not None
        or getattr(report, "run_id", None) is not None
    ):
        raise LiveProductPathError(
            "published_report_receipt_invalid",
            "ready report is not the exact product published from its durable draft",
        )
    document_matches = [
        document
        for document in documents
        if getattr(document, "document_id", None) == getattr(draft, "content_ref", None)
    ]
    if (
        len(document_matches) != 1
        or getattr(document_matches[0], "document_kind", None) != "report_draft_content"
        or getattr(document_matches[0], "invocation_id", None) is not None
    ):
        raise LiveProductPathError(
            "published_report_content_document_invalid",
            "published draft content does not resolve to its durable content document",
        )
    content_document = document_matches[0]
    markdown = str(
        dict(getattr(content_document, "payload", None) or {}).get("markdown") or ""
    )
    if not markdown.strip():
        raise LiveProductPathError(
            "published_report_content_empty",
            "published report draft has no markdown content",
        )
    content = markdown.encode("utf-8")
    report_artifact_id = f"art_report_{_safe_id(str(getattr(report, 'report_id')))}"
    relative_path = f"formal/report/{_safe_id(str(getattr(report, 'report_id')))}.md"
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    content_document_digest = canonical_digest(content_document.to_dict())
    report_artifact = {
        "artifact_id": report_artifact_id,
        "relative_path": relative_path,
        "scope": "formal",
        "origin": "report",
        "kind": "report",
        "provenance": {
            "report_id": str(getattr(report, "report_id")),
            "draft_id": str(getattr(draft, "draft_id")),
            "content_ref": str(getattr(draft, "content_ref")),
            "content_document_digest": content_document_digest,
            "draft_published": True,
        },
    }
    source_refs = [
        dict(item)
        for item in pubmed_provider.get("source_refs") or []
        if isinstance(item, dict)
    ]
    matched_sources = [
        row
        for row in source_refs
        if any(
            marker and marker in markdown
            for marker in (
                str(row.get("source_ref_id") or ""),
                str(row.get("pmid") or ""),
                str(row.get("locator") or ""),
            )
        )
    ]
    matched_artifacts = [
        artifact
        for artifact in scientific_artifacts
        if any(
            marker and marker in markdown
            for marker in (
                str(artifact.record.get("artifact_id") or ""),
                str(
                    dict(artifact.record.get("provenance") or {}).get(
                        "catalog_relative_path"
                    )
                    or ""
                ),
                PurePosixPath(
                    str(
                        dict(artifact.record.get("provenance") or {}).get(
                            "catalog_relative_path"
                        )
                        or ""
                    )
                ).name,
            )
        )
    ]
    if not matched_sources or not matched_artifacts:
        raise LiveProductPathError(
            "published_report_claim_lineage_missing",
            "published markdown does not literally identify PubMed and scientific artifacts",
        )
    product_report_record = dict(report.to_dict())
    published_draft_record = dict(draft.to_dict())
    content_document_record = dict(content_document.to_dict())
    publish_events = _report_publish_event_sequence(
        durable_events,
        report=report,
        draft=draft,
    )
    report_record = {
        "report_id": str(getattr(report, "report_id")),
        "session_id": str(getattr(report, "session_id")),
        "task_id": getattr(report, "task_id", None),
        "lane_id": getattr(report, "lane_id", None),
        "status": "ready",
        "invocation_id": None,
        "run_id": None,
        "product_artifact_id": None,
        "draft_id": str(getattr(draft, "draft_id")),
        "draft_status": "published",
        "published_report_id": str(getattr(report, "report_id")),
        "owner_agent_id": getattr(draft, "owner_agent_id", None),
        "content_ref": str(getattr(draft, "content_ref")),
        "content_document_kind": "report_draft_content",
        "content_document_invocation_id": None,
        "content_document_digest": content_document_digest,
        "content_artifact_id": report_artifact_id,
        "content_digest": _sha256(content),
        "publication_action": "report.publish",
        "product_report_record": product_report_record,
        "published_draft_record": published_draft_record,
        "content_document_record": content_document_record,
        "publish_events": publish_events,
        "cutover_eligible": True,
        "artifact_ids": [
            *(str(artifact.record["artifact_id"]) for artifact in matched_artifacts),
            report_artifact_id,
        ],
        "source_ref_ids": [str(row["source_ref_id"]) for row in matched_sources],
        "claim_source_links": [
            {
                "claim_id": "claim_published_aox_result",
                "source_ref_ids": [
                    str(row["source_ref_id"]) for row in matched_sources
                ],
                "artifact_ids": [
                    str(artifact.record["artifact_id"])
                    for artifact in matched_artifacts
                ],
            }
        ],
    }
    return report_record, report_artifact, publish_events


def _attach_product_receipts(
    context: AttemptRunContext,
    evidence: dict[str, Any],
    *,
    report_publish_events: list[dict[str, object]],
    durable_events: tuple[object, ...],
    browser_approval_receipt: Mapping[str, object] | None,
    formal: SessionDriveResult,
) -> None:
    product_path = dict(evidence["product_path"])
    report = dict(evidence["report"])
    operations = [dict(item) for item in evidence["operations"]]
    providers = [dict(item) for item in evidence["provider_identities"]]
    toolchains = [dict(item) for item in evidence["toolchain_identities"]]
    approvals = [dict(item) for item in evidence["approvals"]]
    tasks = [dict(item) for item in evidence["tasks"]]
    final_answer = dict(evidence["final_answer"])
    outcome = dict(evidence["scientific_outcome"])
    browser_events = _durable_browser_approval_events(
        durable_events,
        browser_receipt=browser_approval_receipt,
        session_id=str(product_path["session_id"]),
    )
    workspace_payload = {
        "schema_id": "aox_workspace_projection_receipt@1",
        "session_id": product_path["session_id"],
        "task_ids_by_role": product_path["task_ids_by_role"],
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "provider_invocation_ids": sorted(item["invocation_id"] for item in providers),
        "toolchain_job_ids": sorted(item["job_id"] for item in toolchains),
        "report_id": report["report_id"],
        "final_master_response_id": product_path["final_master_response_id"],
        "root_identity": product_path["launch_receipt"]["root_identity"],
        "runtime_config_digest": product_path["runtime_config_digest"],
        "cache_hit": product_path["cache_hit"],
        "participant_roles": sorted(product_path["participant_roles"]),
        "task_receipts": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "role": item["role"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "report_receipt": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_artifact_id": report["content_artifact_id"],
            "content_digest": report["content_digest"],
        },
        "final_answer_receipt": {
            "message_id": final_answer["message_id"],
            "content_digest": _sha256(final_answer["content"].encode("utf-8")),
        },
        "scientific_outcome": {
            "status": outcome["status"],
            "candidate_count": outcome["candidate_count"],
            "empty_result_reason": outcome.get("empty_result_reason"),
            "cutover_eligible": outcome["cutover_eligible"],
        },
        "micu_scenario": product_path["micu_scenario"],
        "micu_model": product_path["micu_model"],
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
    }
    event_payload = {
        "schema_id": "aox_event_log_receipt@1",
        "session_id": product_path["session_id"],
        "entry_message_id": product_path["entry_message_id"],
        "entry_message_digest": product_path["entry_message_digest"],
        "final_master_response_id": product_path["final_master_response_id"],
        "task_ids": sorted(product_path["task_ids_by_role"].values()),
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "approval_bindings": sorted(
            (
                {
                    "approval_id": item["approval_id"],
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                }
                for item in approvals
            ),
            key=lambda item: item["approval_id"],
        ),
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
        "task_finishes": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "operation_finishes": sorted(
            (
                {
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                    "status": item["status"],
                    "terminal": item["terminal"],
                }
                for item in operations
            ),
            key=lambda item: item["operation_id"],
        ),
        "provider_invocations": sorted(
            (
                {
                    "invocation_id": item["invocation_id"],
                    "operation_id": item["operation_id"],
                    "provider": item["provider"],
                    "status": item["status"],
                }
                for item in providers
            ),
            key=lambda item: item["invocation_id"],
        ),
        "toolchain_jobs": sorted(
            (
                {
                    "job_id": item["job_id"],
                    "operation_id": item["operation_id"],
                    "tool": item["tool"],
                    "status": item["status"],
                }
                for item in toolchains
            ),
            key=lambda item: item["job_id"],
        ),
        "report_publish": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_digest": report["content_digest"],
            "publish_events": [dict(item) for item in report_publish_events],
        },
        "browser_approval_events": browser_events,
        "browser_approval_event_stream_digest": canonical_digest(browser_events),
    }
    workspace_bytes = canonical_json_bytes(workspace_payload) + b"\n"
    event_bytes = canonical_json_bytes(event_payload) + b"\n"
    workspace_artifact_id = (
        f"art_workspace_projection_{_safe_id(context.roots.attempt_id)}"
    )
    event_artifact_id = f"art_event_log_{_safe_id(context.roots.attempt_id)}"
    workspace_path = "formal/attestation/workspace-projection.json"
    event_path = "formal/attestation/event-log.json"
    _write_sealed_bytes(context.roots.artifact_root, workspace_path, workspace_bytes)
    _write_sealed_bytes(context.roots.artifact_root, event_path, event_bytes)
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": workspace_artifact_id,
                "relative_path": workspace_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {"producer": "host_workspace_projection"},
            },
            {
                "artifact_id": event_artifact_id,
                "relative_path": event_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {"producer": "host_durable_event_log"},
            },
        ]
    )
    product_path["workspace_projection_artifact_id"] = workspace_artifact_id
    product_path["workspace_projection_digest"] = _sha256(workspace_bytes)
    product_path["event_log_artifact_id"] = event_artifact_id
    product_path["event_log_digest"] = _sha256(event_bytes)
    product_path["browser_approval_event_stream_digest"] = canonical_digest(
        browser_events
    )
    product_path["public_final_workspace_digest"] = canonical_digest(formal.workspace)
    product_path["public_final_workspace_response_binding"] = dict(
        formal.workspace_response_binding
    )
    product_path["public_final_event_stream_digest"] = formal.event_receipt.get(
        "event_stream_digest"
    )
    product_path["public_final_event_last_cursor"] = formal.event_receipt.get(
        "last_cursor"
    )
    product_path["public_final_event_response_binding"] = dict(
        formal.event_receipt.get("public_response_binding") or {}
    )
    product_path["public_final_scientific_evidence_digest"] = canonical_digest(
        dict(formal.workspace.get("scientific_evidence") or {})
    )
    final_event_records = [
        dict(item)
        for item in formal.event_receipt.get("event_records") or []
        if isinstance(item, dict)
    ]
    final_event_cursors = [item.get("cursor") for item in final_event_records]
    if (
        len(final_event_records)
        != int(formal.event_receipt.get("event_count") or -1)
        or any(
            item.get("session_id") != formal.session_id
            for item in final_event_records
        )
        or any(
            not isinstance(cursor, int) or isinstance(cursor, bool)
            for cursor in final_event_cursors
        )
        or final_event_cursors != sorted(set(final_event_cursors))
        or formal.event_receipt.get("event_stream_digest")
        != canonical_digest(final_event_records)
        or dict(formal.event_receipt.get("public_response_binding") or {}).get(
            "route"
        )
        != f"/v3/sessions/{formal.session_id}/events?replay=1&after_cursor=0"
    ):
        raise LiveProductPathError(
            "public_final_event_replay_invalid",
            "final public event replay is not a complete ordered same-session preimage",
        )
    final_workspace_payload = {
        "schema_id": "aox_public_final_workspace_snapshot@1",
        "session_id": formal.session_id,
        "workspace": dict(formal.workspace),
        "workspace_digest": canonical_digest(formal.workspace),
        "response_binding": dict(formal.workspace_response_binding),
    }
    final_event_payload = {
        "schema_id": "aox_public_final_event_replay@1",
        "session_id": formal.session_id,
        "replay": True,
        "after_cursor": 0,
        "events": final_event_records,
        "event_count": len(final_event_records),
        "last_cursor": max(final_event_cursors, default=0),
        "event_stream_digest": canonical_digest(final_event_records),
        "response_binding": dict(
            formal.event_receipt.get("public_response_binding") or {}
        ),
    }
    final_workspace_bytes = canonical_json_bytes(final_workspace_payload) + b"\n"
    final_event_bytes = canonical_json_bytes(final_event_payload) + b"\n"
    final_workspace_artifact_id = (
        f"art_public_final_workspace_{_safe_id(context.roots.attempt_id)}"
    )
    final_event_artifact_id = (
        f"art_public_final_events_{_safe_id(context.roots.attempt_id)}"
    )
    final_workspace_path = "formal/attestation/public-final-workspace.json"
    final_event_path = "formal/attestation/public-final-event-replay.json"
    _write_sealed_bytes(
        context.roots.artifact_root,
        final_workspace_path,
        final_workspace_bytes,
    )
    _write_sealed_bytes(
        context.roots.artifact_root,
        final_event_path,
        final_event_bytes,
    )
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": final_workspace_artifact_id,
                "relative_path": final_workspace_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {
                    "producer": "aox_public_final_workspace_snapshot@1"
                },
            },
            {
                "artifact_id": final_event_artifact_id,
                "relative_path": final_event_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {
                    "producer": "aox_public_final_event_replay@1"
                },
            },
        ]
    )
    product_path["public_final_workspace_artifact_id"] = (
        final_workspace_artifact_id
    )
    product_path["public_final_workspace_artifact_digest"] = _sha256(
        final_workspace_bytes
    )
    product_path["public_final_event_replay_artifact_id"] = final_event_artifact_id
    product_path["public_final_event_replay_artifact_digest"] = _sha256(
        final_event_bytes
    )
    evidence["product_path"] = product_path


def _collect_positive_evidence(
    context: AttemptRunContext,
    *,
    provider: SQLiteRepositoryProvider,
    api_receipts: tuple[PublicApiReceipt, ...],
    health: Mapping[str, object],
    probe: SessionDriveResult,
    formal: SessionDriveResult,
    ledger_path: Path,
    micu_record_ids_before: set[int],
) -> dict[str, Any]:
    sandbox_preflight_identity = dict(
        _safe_health(health).get("sandbox_runtime_identity") or {}
    )
    probe_attestation = _collect_probe_attestation(
        context,
        provider=provider,
        probe=probe,
    )
    with provider.read() as scope:
        repositories = scope.repositories
        operations = tuple(
            repositories.controlled_operations.list_by_session(formal.session_id)
        )
        approvals = {
            approval.approval_id: approval
            for approval in repositories.approvals.list_by_session(formal.session_id)
        }
        artifacts = {
            artifact.artifact_id: artifact
            for artifact in repositories.artifacts.list_by_session(formal.session_id)
        }
        sandbox_runs = tuple(
            repositories.sandbox_runs.list_by_session(formal.session_id)
        )
        tasks = tuple(repositories.tasks.list_by_session(formal.session_id))
        agents = tuple(repositories.agents.list_by_session(formal.session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(formal.session_id)
        )
        reports = tuple(repositories.reports.list_by_session(formal.session_id))
        drafts = tuple(repositories.report_drafts.list_by_session(formal.session_id))
        sources = tuple(
            repositories.research_source_refs.list_by_session(formal.session_id)
        )
        invocations = {
            invocation.invocation_id: invocation
            for invocation in repositories.invocations.list_by_session(
                formal.session_id
            )
        }
        conversation = build_conversation_projection(
            repositories,
            formal.session_id,
        )
        durable_events = _durable_events_by_session(
            repositories,
            formal.session_id,
        )
    task_records, task_ids_by_role = _task_receipts(
        tasks=tasks,
        agents=agents,
        documents=documents,
    )
    primary_pubmed = _select_primary_pubmed_evidence(
        sources=sources,
        invocations=invocations,
        artifacts=artifacts,
        task_receipts=task_records,
        task_ids_by_role=task_ids_by_role,
    )
    task_records = _bind_delegation_workflow_receipts(
        context,
        task_receipts=task_records,
        documents=documents,
    )
    formal_hpc_workspace_ids = _require_attempt_hpc_workspace_binding(
        context,
        operations,
    )
    probe_hpc_workspace_id = str(
        dict(probe_attestation.probe.get("isolation") or {}).get("hpc_workspace_id")
        or ""
    )
    attempt_hpc_workspace_ids = formal_hpc_workspace_ids | {
        probe_hpc_workspace_id
    }

    operation_by_role = {
        "ncbi_fetch": _single_completed_operation(
            operations,
            sdk_module="bio",
            function_name="ncbi_fetch_proteins",
        ),
        "reference_alignment": _single_completed_operation(
            operations,
            sdk_module="bio_tools",
            function_name="mafft",
        ),
        "hmm_build": _single_completed_operation(
            operations,
            sdk_module="bio_tools",
            function_name="hmmbuild",
        ),
        "hmmer_search": _single_completed_operation(
            operations,
            sdk_module="bio",
            function_name="hmmer_search",
        ),
    }
    for role, sdk_module, function_name in (
        ("uniprot_fetch", "bio", "uniprot_fetch"),
        ("candidate_alignment", "bio_tools", "hmmalign"),
        ("cdhit", "bio_tools", "cdhit"),
    ):
        optional_operation = _optional_completed_operation(
            operations,
            sdk_module=sdk_module,
            function_name=function_name,
        )
        if optional_operation is not None:
            operation_by_role[role] = optional_operation
    copies: dict[str, CatalogArtifactCopy] = {}
    controlled_records: dict[str, dict[str, object]] = {}
    output_copies: dict[str, list[CatalogArtifactCopy]] = {}
    provider_parameters: dict[str, dict[str, object]] = {}
    provider_response_digests: dict[str, str] = {}
    for role, operation in operation_by_role.items():
        inputs = _declared_operation_input_refs(
            context,
            operation,
            artifacts=artifacts,
            copies=copies,
        )
        if role in {"ncbi_fetch", "hmmer_search", "uniprot_fetch"}:
            params = _provider_request_parameters(
                context,
                operation,
                artifacts=artifacts,
            )
            selected_outputs, response_digest = _provider_output_copies(
                context,
                operation,
                artifacts=artifacts,
                copies=copies,
            )
            provider_parameters[role] = params
            provider_response_digests[role] = response_digest
        else:
            params = None
            selected_outputs = _tool_output_copies(
                context,
                operation,
                artifacts=artifacts,
                copies=copies,
            )
        output_copies[role] = selected_outputs
        controlled_records[role] = operation_evidence_record(
            operation,
            scope="formal",
            inputs=inputs,
            outputs=[_artifact_ref(copy) for copy in selected_outputs],
            parameters=params,
        )

    ncbi_provider_sequences = _copy_with_name(
        output_copies["ncbi_fetch"],
        names={"proteins.fasta"},
        identity="ncbi_provider_sequences",
    )
    reference_alignment = _copy_with_name(
        output_copies["reference_alignment"],
        names={"alignment.fasta"},
        identity="reference_alignment",
    )
    hmm_model = _copy_with_name(
        output_copies["hmm_build"],
        names={"model.hmm"},
        identity="hmm_model",
    )
    hmmer_response = _copy_with_name(
        output_copies["hmmer_search"],
        names={"raw_hits.json"},
        identity="hmmer_response",
    )
    hmmer_parsed_hits = _copy_with_name(
        output_copies["hmmer_search"],
        names={"parsed_hits.csv"},
        identity="hmmer_parsed_hits",
    )
    final_copies, final_artifacts, final_validation = _final_deliverable_copies(
        context,
        artifacts=artifacts,
        copies=copies,
    )
    calculation_run = _sandbox_run_for_final_deliverables(
        final_artifacts,
        sandbox_runs,
    )
    raw_hits = final_copies["aox_hmm/hits_raw.csv"]
    score_filtered_accessions = final_copies[HMMER_SCORE_FILTERED_ACCESSIONS_PATH]
    hmm_reference_set = final_copies["aox_hmm/AOX_ref21.fasta"]
    scoring_reference = final_copies[
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta"
    ]
    scoring_input = final_copies["aox_hmm/AOX_scoring_input.fasta"]
    filtered_hits = final_copies["aox_hmm/hits_len650_700_200.csv"]
    target_sequences = final_copies["aox_hmm/target.fasta"]
    motif_scores = final_copies["aox_hmm/scored_ref_plus_hits.csv"]
    candidates = final_copies["aox_hmm/AOX_candidates.fasta"]
    graph_nodes = final_copies["aox_hmm/nodes.csv"]
    graph_edges = final_copies["aox_hmm/edges_similarity.csv"]
    graph_manifest = final_copies["aox_hmm/similarity_graph_manifest.json"]
    final_scoring_alignment = final_copies["aox_hmm/AOX_scoring_alignment.fasta"]
    final_membership = final_copies["aox_hmm/AOX_candidates_cdhit85.clusters.csv"]
    final_representatives = final_copies["aox_hmm/AOX_candidates_cdhit85.fasta"]

    hmm_reference_result = aox_reference.select_hmm_reference_set(
        ncbi_provider_sequences.content,
        expected_contract_id=(aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID),
        expected_contract_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        expected_input_digest=ncbi_provider_sequences.content_digest,
    )
    scoring_reference_result = aox_reference.select_scoring_reference(
        ncbi_provider_sequences.content,
        expected_contract_id=(aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID),
        expected_contract_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
        expected_input_digest=ncbi_provider_sequences.content_digest,
    )
    if hmm_reference_set.content != hmm_reference_result.to_fasta().encode(
        "utf-8"
    ) or scoring_reference.content != scoring_reference_result.to_fasta().encode(
        "utf-8"
    ):
        raise LiveProductPathError(
            "aox_reference_selection_mismatch",
            "sealed model/scoring references differ from the versioned NCBI selection contracts",
        )
    reference_alignment_inputs = {
        str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
        for ref in controlled_records["reference_alignment"].get("inputs") or []
        if isinstance(ref, dict)
    }
    if reference_alignment_inputs != {
        str(hmm_reference_set.record["artifact_id"]): hmm_reference_set.content_digest
    }:
        raise LiveProductPathError(
            "hmm_reference_selection_not_consumed",
            "MAFFT must consume the exact selected 13-reference artifact, not the 14-record provider response",
        )

    if raw_hits.content != hmmer_parsed_hits.content:
        raise LiveProductPathError(
            "hmmer_raw_hit_normalization_drift",
            "normalized hits_raw.csv differs from the sealed EBI parsed-hit bytes",
        )
    score_filter_result = _score_filtered_hmmer_accessions(
        hmmer_parsed_hits.content,
        score_filtered_accessions.content,
    )
    derived_accessions = list(score_filter_result.accessions)
    hmmer_upstream_empty = not derived_accessions
    upstream_empty_reason = (
        "no_hmmer_hits"
        if hmmer_upstream_empty and score_filter_result.input_row_count == 0
        else "no_filtered_hmmer_accessions"
        if hmmer_upstream_empty
        else None
    )
    uniprot_sequences: CatalogArtifactCopy | None = None
    uniprot_metadata: CatalogArtifactCopy | None = None
    uniprot_raw_response: CatalogArtifactCopy | None = None
    sequence_join_result: aox_sequence_join.SequenceLengthJoinResult | None = None
    if hmmer_upstream_empty:
        if "uniprot_fetch" in operation_by_role:
            raise LiveProductPathError(
                "upstream_empty_uniprot_operation_forbidden",
                "UniProt must not be called when the sealed HMMER score filter is empty",
            )
        expected_empty_hits = (
            ",".join(aox_sequence_join.OUTPUT_COLUMNS) + "\n"
        ).encode("utf-8")
        if filtered_hits.content != expected_empty_hits or target_sequences.content:
            raise LiveProductPathError(
                "upstream_empty_materialization_invalid",
                "HMMER upstream-empty branch requires canonical empty joined hits and target FASTA",
            )
    else:
        if "uniprot_fetch" not in operation_by_role:
            raise LiveProductPathError(
                "required_uniprot_operation_missing",
                "nonempty HMMER accessions require one controlled UniProt operation",
            )
        uniprot_sequences = _copy_with_name(
            output_copies["uniprot_fetch"],
            names={"sequences.fasta"},
            identity="uniprot_sequences",
        )
        uniprot_metadata = _copy_with_name(
            output_copies["uniprot_fetch"],
            names={"metadata.json"},
            identity="uniprot_metadata",
        )
        uniprot_raw_response = _copy_with_name(
            output_copies["uniprot_fetch"],
            names={"pages.json"},
            identity="uniprot_raw_response",
        )
        if not _raw_provider_response_digests(uniprot_raw_response.content):
            raise LiveProductPathError(
                "uniprot_raw_response_invalid",
                "sealed UniProt pages.json is not one strict raw HTTP response envelope",
            )
        uniprot_params = provider_parameters["uniprot_fetch"]
        source_hit_artifact = dict(uniprot_params.get("source_hit_artifact") or {})
        if sorted(
            str(item).strip().upper() for item in uniprot_params.get("accessions") or []
        ) != derived_accessions or source_hit_artifact != {
            "artifact_id": str(score_filtered_accessions.record["artifact_id"]),
            "content_digest": score_filtered_accessions.content_digest,
        }:
            raise LiveProductPathError(
                "hmmer_uniprot_dependency_mismatch",
                "sealed UniProt request does not bind the exact derived HMMER accession artifact",
            )
        try:
            sequence_join_result = aox_sequence_join.join_score_filtered_accessions(
                score_filtered_accessions.content,
                uniprot_sequences.content,
                uniprot_metadata.content,
                expected_contract_id=aox_sequence_join.CONTRACT_ID,
                expected_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
                expected_implementation_digest=(
                    aox_sequence_join.IMPLEMENTATION_DIGEST
                ),
                expected_hmmer_contract_id=aox_hmmer.CONTRACT_ID,
                expected_hmmer_contract_digest=aox_hmmer.CONTRACT_DIGEST,
                expected_hmmer_implementation_digest=(aox_hmmer.IMPLEMENTATION_DIGEST),
                expected_score_filtered_csv_digest=(
                    score_filtered_accessions.content_digest
                ),
                expected_uniprot_fasta_digest=uniprot_sequences.content_digest,
                expected_uniprot_metadata_digest=uniprot_metadata.content_digest,
            )
        except ValueError as exc:
            raise LiveProductPathError(
                "sequence_length_join_invalid",
                "sealed UniProt outputs do not satisfy aox_sequence_length_join@2",
            ) from exc
        if filtered_hits.content != sequence_join_result.hits_csv().encode(
            "utf-8"
        ) or target_sequences.content != sequence_join_result.target_fasta().encode(
            "utf-8"
        ):
            raise LiveProductPathError(
                "sequence_length_join_output_mismatch",
                "normalized post-UniProt hits or target FASTA differ from offline recomputation",
            )

    scoring_input_result = aox_reference.assemble_scoring_input(
        scoring_reference.content,
        target_sequences.content,
        expected_contract_id=aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
        expected_contract_digest=(aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST),
        expected_implementation_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        ),
        expected_scoring_reference_input_digest=scoring_reference.content_digest,
        expected_target_input_digest=target_sequences.content_digest,
    )
    if scoring_input.content != scoring_input_result.to_fasta().encode("utf-8"):
        raise LiveProductPathError(
            "aox_scoring_input_assembly_mismatch",
            "sealed scoring input differs from the versioned AAB-plus-target assembly contract",
        )

    target_sequences_nonempty = bool(target_sequences.content.strip())
    if target_sequences_nonempty:
        if "candidate_alignment" not in operation_by_role:
            raise LiveProductPathError(
                "required_hmmalign_operation_missing",
                "nonempty post-UniProt targets require one controlled HMMalign operation",
            )
        scoring_alignment = _copy_with_name(
            output_copies["candidate_alignment"],
            names={"aligned.fasta"},
            identity="scoring_alignment",
        )
        if scoring_alignment.content != final_scoring_alignment.content:
            raise LiveProductPathError(
                "scoring_alignment_normalization_drift",
                "normalized scoring alignment differs from the HMMalign output bytes",
            )
        candidate_alignment_inputs = {
            str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
            for ref in controlled_records["candidate_alignment"].get("inputs") or []
            if isinstance(ref, dict)
        }
        if candidate_alignment_inputs != {
            str(hmm_model.record["artifact_id"]): hmm_model.content_digest,
            str(scoring_input.record["artifact_id"]): scoring_input.content_digest,
        }:
            raise LiveProductPathError(
                "hmmalign_scoring_input_mismatch",
                "HMMalign must consume the exact HMM plus versioned AAB-and-target scoring input",
            )
    else:
        if "candidate_alignment" in operation_by_role:
            raise LiveProductPathError(
                "empty_target_hmmalign_operation_forbidden",
                "HMMalign must be omitted when the sealed target FASTA is empty",
            )
        scoring_alignment = final_scoring_alignment
        if scoring_alignment.content != scoring_reference.content:
            raise LiveProductPathError(
                "reference_only_scoring_alignment_invalid",
                "empty-target scoring alignment must equal the sealed normalized reference FASTA",
            )

    candidate_count = int(final_validation["candidate_count"])
    if candidate_count:
        if "cdhit" not in operation_by_role:
            raise LiveProductPathError(
                "required_cdhit_operation_missing",
                "nonempty AOX candidates require one controlled CD-HIT operation",
            )
        cdhit_membership = _copy_with_name(
            output_copies["cdhit"],
            names={"clusters.csv"},
            identity="cdhit_membership",
        )
        cdhit_representatives = _copy_with_name(
            output_copies["cdhit"],
            names={"clustered.fasta"},
            identity="cdhit_representatives",
        )
        if (
            cdhit_membership.content != final_membership.content
            or cdhit_representatives.content != final_representatives.content
        ):
            raise LiveProductPathError(
                "cdhit_membership_normalization_drift",
                "normalized CD-HIT outputs differ from the controlled output bytes",
            )
    else:
        if "cdhit" in operation_by_role:
            raise LiveProductPathError(
                "empty_candidate_cdhit_operation_forbidden",
                "CD-HIT must be omitted when the sealed candidate FASTA is empty",
            )
        cdhit_membership = final_membership
        cdhit_representatives = final_representatives

    all_controlled_outputs: list[dict[str, str]] = []
    seen_output_ids: set[str] = set()
    for role in operation_by_role:
        for copy in output_copies[role]:
            artifact_id = str(copy.record["artifact_id"])
            if artifact_id not in seen_output_ids:
                seen_output_ids.add(artifact_id)
                all_controlled_outputs.append(_artifact_ref(copy))
    specialized_paths = {
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
        "aox_hmm/AOX_scoring_input.fasta",
        "aox_hmm/AOX_scoring_alignment.fasta",
        "aox_hmm/hits_len650_700_200.csv",
        "aox_hmm/target.fasta",
        HMMER_SCORE_FILTERED_ACCESSIONS_PATH,
        "aox_hmm/scored_ref_plus_hits.csv",
        "aox_hmm/AOX_candidates.fasta",
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/similarity_graph_manifest.json",
    }
    if not candidate_count:
        specialized_paths.update(
            {
                "aox_hmm/AOX_candidates_cdhit85.fasta",
                "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
            }
        )
    normalization_outputs = [
        _artifact_ref(final_copies[path])
        for path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES - specialized_paths)
    ]
    source_implementation_digest = _sandbox_source_implementation_digest(
        calculation_run,
        AOX_DELIVERABLE_NORMALIZATION_ID,
    )
    normalization_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="deliverable_normalization",
        calculation_id=AOX_DELIVERABLE_NORMALIZATION_ID,
        calculation_contract_digest=AOX_DELIVERABLE_NORMALIZATION_CONTRACT_DIGEST,
        calculation_implementation_digest=source_implementation_digest,
        parameters={"deliverable_count": len(S15_AOX_HMM_FIXED_DELIVERABLES)},
        inputs=all_controlled_outputs,
        outputs=normalization_outputs,
    )
    hmm_reference_selection_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="hmm_reference_set_selection",
        calculation_id=aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        calculation_contract_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        calculation_implementation_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        parameters={
            "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
            "identity_replacement": False,
        },
        inputs=[_artifact_ref(ncbi_provider_sequences)],
        outputs=[_artifact_ref(hmm_reference_set)],
    )
    scoring_reference_selection_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="scoring_reference_selection",
        calculation_id=aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID,
        calculation_contract_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        ),
        calculation_implementation_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
        parameters={
            "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
            "identity_replacement": False,
        },
        inputs=[_artifact_ref(ncbi_provider_sequences)],
        outputs=[_artifact_ref(scoring_reference)],
    )
    scoring_input_assembly_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="scoring_input_assembly",
        calculation_id=aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
        calculation_contract_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        ),
        calculation_implementation_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        ),
        parameters={
            "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
            "target_count": len(scoring_input_result.targets),
        },
        inputs=[_artifact_ref(scoring_reference), _artifact_ref(target_sequences)],
        outputs=[_artifact_ref(scoring_input)],
    )
    pre_uniprot_score_filter_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="pre_uniprot_score_filter",
        calculation_id=aox_hmmer.CONTRACT_ID,
        calculation_contract_digest=aox_hmmer.CONTRACT_DIGEST,
        calculation_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
        parameters={"hmm_score_exclusive_gt": aox_hmmer.SCORE_THRESHOLD_DISPLAY},
        inputs=[_artifact_ref(hmmer_parsed_hits)],
        outputs=[_artifact_ref(score_filtered_accessions)],
    )
    post_uniprot_filter_operation: dict[str, object] | None = None
    upstream_empty_materialization_operation: dict[str, object] | None = None
    empty_target_scoring_operation: dict[str, object] | None = None
    if hmmer_upstream_empty:
        upstream_empty_materialization_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="upstream_empty_materialization",
            calculation_id=AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
            calculation_contract_digest=(
                AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST
            ),
            calculation_implementation_digest=_sandbox_source_implementation_digest(
                calculation_run,
                AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
            ),
            parameters={
                "reason": upstream_empty_reason or "",
                "reference_accession": aox_motif.REFERENCE_ACCESSION,
            },
            inputs=[
                _artifact_ref(score_filtered_accessions),
            ],
            outputs=[
                _artifact_ref(filtered_hits),
                _artifact_ref(target_sequences),
            ],
        )
    else:
        assert uniprot_sequences is not None
        assert uniprot_metadata is not None
        post_uniprot_filter_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="post_uniprot_filter",
            calculation_id=aox_sequence_join.CONTRACT_ID,
            calculation_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
            calculation_implementation_digest=aox_sequence_join.IMPLEMENTATION_DIGEST,
            parameters={
                "length_inclusive": [
                    aox_sequence_join.LENGTH_MIN,
                    aox_sequence_join.LENGTH_MAX,
                ],
            },
            inputs=[
                _artifact_ref(score_filtered_accessions),
                _artifact_ref(uniprot_sequences),
                _artifact_ref(uniprot_metadata),
            ],
            outputs=[_artifact_ref(filtered_hits), _artifact_ref(target_sequences)],
        )
    if not target_sequences_nonempty:
        empty_target_scoring_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="empty_target_scoring_materialization",
            calculation_id=AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
            calculation_contract_digest=(
                AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST
            ),
            calculation_implementation_digest=(
                _sandbox_source_implementation_digest(
                    calculation_run,
                    AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
                )
            ),
            parameters={
                "reason": upstream_empty_reason or "no_candidates_after_length_filter",
                "reference_accession": aox_motif.REFERENCE_ACCESSION,
            },
            inputs=[
                _artifact_ref(scoring_input),
                _artifact_ref(target_sequences),
            ],
            outputs=[_artifact_ref(scoring_alignment)],
        )
    motif_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="motif_score",
        calculation_id=aox_motif.CONTRACT_ID,
        calculation_contract_digest=aox_motif.CONTRACT_DIGEST,
        calculation_implementation_digest=aox_motif.IMPLEMENTATION_DIGEST,
        parameters={
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
            "threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        },
        inputs=[_artifact_ref(scoring_alignment)],
        outputs=[_artifact_ref(motif_scores)],
    )
    candidate_filter_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="candidate_filter",
        calculation_id=AOX_CANDIDATE_FILTER_ID,
        calculation_contract_digest=AOX_CANDIDATE_FILTER_CONTRACT_DIGEST,
        calculation_implementation_digest=_sandbox_source_implementation_digest(
            calculation_run,
            AOX_CANDIDATE_FILTER_ID,
        ),
        parameters={
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
            "threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        },
        inputs=[_artifact_ref(motif_scores), _artifact_ref(target_sequences)],
        outputs=[_artifact_ref(candidates)],
    )
    empty_membership_operation: dict[str, object] | None = None
    if not candidate_count:
        empty_membership_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="empty_membership",
            calculation_id=AOX_EMPTY_MEMBERSHIP_ID,
            calculation_contract_digest=AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST,
            calculation_implementation_digest=_sandbox_source_implementation_digest(
                calculation_run,
                AOX_EMPTY_MEMBERSHIP_ID,
            ),
            parameters={
                "identity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
            },
            inputs=[_artifact_ref(candidates)],
            outputs=[
                _artifact_ref(cdhit_representatives),
                _artifact_ref(cdhit_membership),
            ],
        )
    similarity_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="similarity",
        calculation_id=aox_similarity.CALCULATION_ID,
        calculation_contract_digest=aox_similarity.CALCULATION_DIGEST,
        calculation_implementation_digest=aox_similarity.IMPLEMENTATION_DIGEST,
        parameters={"threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM},
        inputs=[_artifact_ref(candidates), _artifact_ref(cdhit_membership)],
        outputs=[
            _artifact_ref(graph_nodes),
            _artifact_ref(graph_edges),
            _artifact_ref(graph_manifest),
        ],
    )

    pubmed_invocation = primary_pubmed.invocation
    document_by_id = {
        str(getattr(document, "document_id")): document for document in documents
    }
    pubmed_input_document = document_by_id.get(
        str(getattr(pubmed_invocation, "input_ref", "") or "")
    )
    pubmed_output_document = document_by_id.get(
        str(getattr(pubmed_invocation, "output_ref", "") or "")
    )
    if pubmed_input_document is None or pubmed_output_document is None:
        raise LiveProductPathError(
            "pubmed_engine_document_missing",
            "PubMed engine invocation lacks its durable input or output document",
        )
    pubmed_provider, pubmed_engine_invocation, literature_evidence = _pubmed_receipts(
        context,
        sources=primary_pubmed.sources,
        invocation=pubmed_invocation,
        input_document=pubmed_input_document,
        output_document=pubmed_output_document,
        artifacts=artifacts,
        copies=copies,
    )

    ncbi_provider_record = _controlled_provider_receipt(
        provider_name="ncbi",
        operation=operation_by_role["ncbi_fetch"],
        operation_record=controlled_records["ncbi_fetch"],
        output_copies=output_copies["ncbi_fetch"],
        response_digest=provider_response_digests["ncbi_fetch"],
    )
    hmmer_provider_record = _controlled_provider_receipt(
        provider_name="ebi_hmmer",
        operation=operation_by_role["hmmer_search"],
        operation_record=controlled_records["hmmer_search"],
        output_copies=output_copies["hmmer_search"],
        response_digest=provider_response_digests["hmmer_search"],
    )
    upstream_empty_artifact_record: dict[str, object] | None = None
    if hmmer_upstream_empty:
        assert upstream_empty_reason is not None
        uniprot_provider_record, upstream_empty_artifact_record = (
            _upstream_empty_provider_receipt(
                context,
                upstream_provider_record=hmmer_provider_record,
                derivation_operation=pre_uniprot_score_filter_operation,
                derived_accession_artifact=score_filtered_accessions,
                reason=upstream_empty_reason,
            )
        )
    else:
        uniprot_provider_record = _controlled_provider_receipt(
            provider_name="uniprot",
            operation=operation_by_role["uniprot_fetch"],
            operation_record=controlled_records["uniprot_fetch"],
            output_copies=output_copies["uniprot_fetch"],
            response_digest=provider_response_digests["uniprot_fetch"],
        )
    provider_records = [
        pubmed_provider,
        ncbi_provider_record,
        hmmer_provider_record,
        uniprot_provider_record,
    ]
    provider_by_name = {str(item["provider"]): item for item in provider_records}

    toolchain_records = [
        _toolchain_receipt(
            tool_name=tool_name,
            operation=operation_by_role[role],
            operation_record=controlled_records[role],
        )
        for role, tool_name in (
            ("reference_alignment", "mafft"),
            ("hmm_build", "hmmbuild"),
            ("candidate_alignment", "hmmalign"),
            ("cdhit", "cd-hit"),
        )
        if role in operation_by_role
    ]
    approval_records = [
        _approval_record(operation, approvals)
        for operation in operation_by_role.values()
    ]
    if (
        pubmed_engine_invocation["task_id"] != task_ids_by_role["researcher"]
        or pubmed_engine_invocation["lane_id"]
        != primary_pubmed.researcher_task.get("lane_id")
    ):
        raise LiveProductPathError(
            "pubmed_research_task_mismatch",
            "PubMed invocation is not owned by the exact formal researcher scope",
        )

    scoring_result = aox_motif.score_aligned_fasta(scoring_alignment.content)
    if not target_sequences_nonempty and {
        row.sequence_id for row in scoring_result.rows
    } != {aox_motif.REFERENCE_ACCESSION}:
        raise LiveProductPathError(
            "empty_target_scoring_alignment_invalid",
            "empty-target scoring alignment must contain only the exact AOX reference",
        )
    if motif_scores.content != scoring_result.to_csv().encode("utf-8"):
        raise LiveProductPathError(
            "motif_score_recomputation_mismatch",
            "sealed motif score CSV differs from offline contract recomputation",
        )
    execution_summary = json.loads(
        final_copies["aox_hmm/execution_summary.json"].content
    )
    if not isinstance(execution_summary, dict):
        raise LiveProductPathError(
            "execution_summary_invalid",
            "normalized execution summary must be a JSON object",
        )
    empty_result_reason = None
    if candidate_count == 0:
        empty_payload = execution_summary.get("empty_result")
        empty_result_reason = (
            str(dict(empty_payload).get("reason") or "").strip()
            if isinstance(empty_payload, dict)
            else ""
        )
        if not empty_result_reason:
            raise LiveProductPathError(
                "empty_result_reason_missing",
                "healthy empty AOX result lacks its explicit scientific reason",
            )
        expected_empty_reason = (
            upstream_empty_reason
            if hmmer_upstream_empty
            else "no_candidates_after_length_filter"
            if not target_sequences_nonempty
            else "no_candidates_after_motif_filter"
        )
        if empty_result_reason != expected_empty_reason:
            raise LiveProductPathError(
                "empty_result_reason_mismatch",
                "execution summary empty reason does not match the sealed branch trigger",
                details={
                    "expected": expected_empty_reason,
                    "actual": empty_result_reason,
                },
            )
    graph_result = aox_similarity.validate_graph_artifacts(
        candidates.content,
        cdhit_membership.content,
        graph_nodes.content,
        graph_edges.content,
        graph_manifest.content,
        threshold_ppm=aox_similarity.DEFAULT_THRESHOLD_PPM,
        empty_result_reason=empty_result_reason,
    )
    if len(graph_result.nodes) != candidate_count:
        raise LiveProductPathError(
            "scientific_outcome_graph_mismatch",
            "offline graph node count differs from the validated AOX candidates",
        )

    report_record, report_artifact, report_publish_events = _published_report_receipt(
        context,
        reports=reports,
        drafts=drafts,
        documents=documents,
        durable_events=durable_events,
        pubmed_provider=pubmed_provider,
        scientific_artifacts=list(copies.values()),
    )
    if report_record["task_id"] != task_ids_by_role["reporter"]:
        raise LiveProductPathError(
            "published_report_task_mismatch",
            "published report is not owned by the formal reporter task",
        )

    user_messages = [entry for entry in conversation if entry.role == "user"]
    assistant_messages = [
        entry
        for entry in conversation
        if entry.role == "assistant" and entry.content.strip()
    ]
    message_route = f"/v3/sessions/{formal.session_id}/messages"
    message_receipts = [
        receipt
        for receipt in api_receipts
        if receipt.method == "POST" and receipt.route == message_route
    ]
    if len(user_messages) != 1 or not assistant_messages or len(message_receipts) != 1:
        raise LiveProductPathError(
            "canonical_entry_message_invalid",
            "formal product path must originate from one public user message and produce an answer",
        )
    entry_message = user_messages[0]
    final_message = assistant_messages[-1]
    micu_receipts = _new_micu_attempt_receipts(
        ledger_path,
        before_ids=micu_record_ids_before,
    )
    micu_models = {receipt.model for receipt in micu_receipts}
    if len(micu_models) != 1:
        raise LiveProductPathError(
            "micu_attempt_model_ambiguous",
            "AOX live campaign charged more than one MICU model identity",
        )
    participant_roles = sorted(
        {
            str(getattr(agent, "role"))
            for agent in agents
            if str(getattr(agent, "role", "")) != "master"
        }
    )
    product_path = {
        "entry_message_count": 1,
        "canonical_api_only": True,
        "cache_hit": False,
        "participant_roles": participant_roles,
        "session_id": formal.session_id,
        "entry_message_id": entry_message.message_id,
        "final_master_response_id": final_message.message_id,
        "entry_message_digest": _sha256(entry_message.content.encode("utf-8")),
        "runtime_config_digest": str(context.identity["config_digest"]),
        "micu_scenario": "aox_blank_world_cutover",
        "micu_model": next(iter(micu_models)),
        "micu_invocation_ids": [receipt.invocation_id for receipt in micu_receipts],
        "task_ids_by_role": task_ids_by_role,
        "launch_receipt": {
            "root_identity": context.roots.proof["root_identity"],
            "hpc_workspace_label": context.roots.hpc_workspace_label,
            "sqlite_initialized_fresh": True,
            "artifact_root_bound": True,
            "blob_root_bound": True,
            "sandbox_root_bound": True,
            "sandbox_runtime_identity": sandbox_preflight_identity,
        },
        "hpc_workspace_binding": {
            "schema_id": AOX_HPC_WORKSPACE_BINDING_CONTRACT_ID,
            "label": context.roots.hpc_workspace_label,
            "workspace_ids": sorted(attempt_hpc_workspace_ids),
        },
    }

    formal_operations = [
        *controlled_records.values(),
        normalization_operation,
        hmm_reference_selection_operation,
        scoring_reference_selection_operation,
        scoring_input_assembly_operation,
        pre_uniprot_score_filter_operation,
    ]
    for optional_calculation in (
        post_uniprot_filter_operation,
        upstream_empty_materialization_operation,
        empty_target_scoring_operation,
        empty_membership_operation,
    ):
        if optional_calculation is not None:
            formal_operations.append(optional_calculation)
    formal_operations.extend(
        [
            motif_operation,
            candidate_filter_operation,
            similarity_operation,
        ]
    )
    operation_roles = {
        **{
            role: operation.operation_id
            for role, operation in operation_by_role.items()
        },
        "hmm_reference_set_selection": hmm_reference_selection_operation[
            "operation_id"
        ],
        "scoring_reference_selection": scoring_reference_selection_operation[
            "operation_id"
        ],
        "scoring_input_assembly": scoring_input_assembly_operation["operation_id"],
        "pre_uniprot_score_filter": pre_uniprot_score_filter_operation["operation_id"],
        "motif_score": motif_operation["operation_id"],
        "candidate_filter": candidate_filter_operation["operation_id"],
        "similarity": similarity_operation["operation_id"],
    }
    if post_uniprot_filter_operation is not None:
        operation_roles["post_uniprot_filter"] = post_uniprot_filter_operation[
            "operation_id"
        ]
    if upstream_empty_materialization_operation is not None:
        operation_roles["upstream_empty_materialization"] = (
            upstream_empty_materialization_operation["operation_id"]
        )
    if empty_target_scoring_operation is not None:
        operation_roles["empty_target_scoring_materialization"] = (
            empty_target_scoring_operation["operation_id"]
        )
    if empty_membership_operation is not None:
        operation_roles["empty_membership"] = empty_membership_operation["operation_id"]
    artifact_roles = {
        "literature_evidence": str(literature_evidence.record["artifact_id"]),
        "ncbi_provider_sequences": str(ncbi_provider_sequences.record["artifact_id"]),
        "hmm_reference_set": str(hmm_reference_set.record["artifact_id"]),
        "scoring_reference": str(scoring_reference.record["artifact_id"]),
        "scoring_input": str(scoring_input.record["artifact_id"]),
        "reference_alignment": str(reference_alignment.record["artifact_id"]),
        "hmm_model": str(hmm_model.record["artifact_id"]),
        "hmmer_response": str(hmmer_response.record["artifact_id"]),
        "hmmer_parsed_hits": str(hmmer_parsed_hits.record["artifact_id"]),
        "hmmer_score_filtered_accessions": str(
            score_filtered_accessions.record["artifact_id"]
        ),
        "post_uniprot_filtered_hits": str(filtered_hits.record["artifact_id"]),
        "target_sequences": str(target_sequences.record["artifact_id"]),
        "scoring_alignment": str(scoring_alignment.record["artifact_id"]),
        "motif_scores": str(motif_scores.record["artifact_id"]),
        "candidates": str(candidates.record["artifact_id"]),
        "cdhit_membership": str(cdhit_membership.record["artifact_id"]),
        "graph_nodes": str(graph_nodes.record["artifact_id"]),
        "graph_edges": str(graph_edges.record["artifact_id"]),
        "graph_manifest": str(graph_manifest.record["artifact_id"]),
    }
    if uniprot_sequences is not None and uniprot_metadata is not None:
        assert uniprot_raw_response is not None
        artifact_roles.update(
            {
                "uniprot_sequences": str(uniprot_sequences.record["artifact_id"]),
                "uniprot_metadata": str(uniprot_metadata.record["artifact_id"]),
                "uniprot_raw_response": str(
                    uniprot_raw_response.record["artifact_id"]
                ),
            }
        )
    provider_dependency: dict[str, object] = {
        "upstream_provider_record_id": provider_by_name["ebi_hmmer"][
            "provider_record_id"
        ],
        "upstream_response_artifact_ids": [str(hmmer_response.record["artifact_id"])],
        "derivation_id": aox_hmmer.CONTRACT_ID,
        "derivation_operation_id": pre_uniprot_score_filter_operation["operation_id"],
        "parsed_hit_artifact_id": str(hmmer_parsed_hits.record["artifact_id"]),
        "parsed_hit_artifact_digest": hmmer_parsed_hits.content_digest,
        "derived_accession_artifact_id": str(
            score_filtered_accessions.record["artifact_id"]
        ),
        "derived_accession_artifact_digest": (score_filtered_accessions.content_digest),
        "derivation_contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "derivation_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "derived_accessions": derived_accessions,
        "derived_accessions_digest": canonical_digest(derived_accessions),
        "downstream_provider_record_id": provider_by_name["uniprot"][
            "provider_record_id"
        ],
    }
    empty_branch: dict[str, object] | None = None
    if not candidate_count:
        empty_stage = (
            "pre_uniprot_score_filter"
            if hmmer_upstream_empty
            else "sequence_length_join"
            if not target_sequences_nonempty
            else "motif_candidate_filter"
        )
        trigger_copy = (
            score_filtered_accessions
            if hmmer_upstream_empty
            else target_sequences
            if not target_sequences_nonempty
            else candidates
        )
        empty_branch = {
            "schema_id": "aox_empty_branch@1",
            "stage": empty_stage,
            "reason": empty_result_reason or "",
            "trigger_artifact_id": str(trigger_copy.record["artifact_id"]),
            "trigger_artifact_digest": trigger_copy.content_digest,
            "observed_count_before": (
                score_filter_result.input_row_count
                if hmmer_upstream_empty
                else len(sequence_join_result.input_hits)
                if not target_sequences_nonempty and sequence_join_result is not None
                else len(sequence_join_result.hits)
                if sequence_join_result is not None
                else 0
            ),
            "observed_count_after": 0,
            "derivation_operation_id": (
                pre_uniprot_score_filter_operation["operation_id"]
                if hmmer_upstream_empty
                else post_uniprot_filter_operation["operation_id"]
                if not target_sequences_nonempty
                and post_uniprot_filter_operation is not None
                else candidate_filter_operation["operation_id"]
            ),
            "skip_provider_record_id": (
                provider_by_name["uniprot"]["provider_record_id"]
                if hmmer_upstream_empty
                else None
            ),
            "omitted_controlled_roles": [
                role
                for role in ("uniprot_fetch", "candidate_alignment", "cdhit")
                if role not in operation_by_role
            ],
            "empty_materialization_operation_id": (
                upstream_empty_materialization_operation["operation_id"]
                if upstream_empty_materialization_operation is not None
                else empty_target_scoring_operation["operation_id"]
                if empty_target_scoring_operation is not None
                else None
            ),
            "empty_membership_operation_id": (
                None
                if empty_membership_operation is None
                else empty_membership_operation["operation_id"]
            ),
        }
    if hmmer_upstream_empty:
        provider_dependency.update(
            {
                "terminal_empty_reason": upstream_empty_reason,
                "skip_receipt_digest": uniprot_provider_record["skip_receipt_digest"],
                "skip_artifact_id": uniprot_provider_record["artifact_ids"][0],
            }
        )
    sequence_join_check: dict[str, object] | None = None
    if sequence_join_result is not None:
        assert uniprot_sequences is not None
        assert uniprot_metadata is not None
        assert uniprot_raw_response is not None
        sequence_join_check = {
            "score_filtered_artifact_id": str(
                score_filtered_accessions.record["artifact_id"]
            ),
            "uniprot_fasta_artifact_id": str(uniprot_sequences.record["artifact_id"]),
            "uniprot_metadata_artifact_id": str(uniprot_metadata.record["artifact_id"]),
            "uniprot_raw_response_artifact_id": str(
                uniprot_raw_response.record["artifact_id"]
            ),
            "filtered_hits_artifact_id": str(filtered_hits.record["artifact_id"]),
            "target_fasta_artifact_id": str(target_sequences.record["artifact_id"]),
            "contract_id": aox_sequence_join.CONTRACT_ID,
            "contract_digest": aox_sequence_join.CONTRACT_DIGEST,
            "implementation_digest": aox_sequence_join.IMPLEMENTATION_DIGEST,
            "metadata": sequence_join_result.metadata(),
        }
    evidence: dict[str, Any] = {
        "provider_identities": provider_records,
        "engine_invocations": [pubmed_engine_invocation],
        "toolchain_identities": toolchain_records,
        "known_positive_probe": probe_attestation.probe,
        "product_path": product_path,
        "approvals": [*probe_attestation.approvals, *approval_records],
        "operations": [*probe_attestation.operations, *formal_operations],
        "tasks": task_records,
        "artifacts": [
            *probe_attestation.artifacts,
            *(copy.record for copy in copies.values()),
            *(
                []
                if upstream_empty_artifact_record is None
                else [upstream_empty_artifact_record]
            ),
            report_artifact,
        ],
        "report": report_record,
        "final_answer": {
            "message_id": final_message.message_id,
            "content": final_message.content,
        },
        "scientific_checks": {
            "scoring": {
                "alignment_artifact_id": str(scoring_alignment.record["artifact_id"]),
                "scored_artifact_id": str(motif_scores.record["artifact_id"]),
                "scoring_contract_id": aox_motif.CONTRACT_ID,
                "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
                "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
                "input_digest": scoring_result.alignment.input_digest,
            },
            **(
                {}
                if sequence_join_check is None
                else {"sequence_join": sequence_join_check}
            ),
            "similarity": {
                "candidate_fasta_artifact_id": str(candidates.record["artifact_id"]),
                "membership_artifact_id": str(cdhit_membership.record["artifact_id"]),
                "nodes_artifact_id": str(graph_nodes.record["artifact_id"]),
                "edges_artifact_id": str(graph_edges.record["artifact_id"]),
                "manifest_artifact_id": str(graph_manifest.record["artifact_id"]),
                "threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
                "empty_result_reason": empty_result_reason,
                "calculation_id": aox_similarity.CALCULATION_ID,
                "calculation_digest": aox_similarity.CALCULATION_DIGEST,
                "implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
                "candidate_fasta_digest": graph_result.sequences.input_digest,
                "membership_digest": graph_result.membership.input_digest,
            },
            "aox_chain": {
                "literature_provider_record_id": pubmed_provider["provider_record_id"],
                "operation_roles": operation_roles,
                "provider_dependencies": [provider_dependency],
                "artifact_roles": artifact_roles,
                "excluded_scoring_sequence_ids": [aox_motif.REFERENCE_ACCESSION],
                "empty_branch": empty_branch,
            },
        },
        "warnings": [],
        "degradations": [],
        "scientific_outcome": {
            "status": "discovered" if candidate_count else "empty",
            "candidate_count": candidate_count,
            "empty_result_reason": empty_result_reason,
            "cutover_eligible": True,
        },
        "fault_injection": None,
    }
    _attach_product_receipts(
        context,
        evidence,
        report_publish_events=report_publish_events,
        durable_events=durable_events,
        browser_approval_receipt=formal.browser_approval_receipt,
        formal=formal,
    )
    return evidence


def _attach_fault_public_final_snapshot_artifacts(
    context: AttemptRunContext,
    evidence: dict[str, Any],
    *,
    formal: SessionDriveResult,
) -> None:
    product_path = dict(evidence["product_path"])
    events = [
        dict(item)
        for item in formal.event_receipt.get("event_records") or []
        if isinstance(item, dict)
    ]
    cursors = [item.get("cursor") for item in events]
    event_binding = dict(formal.event_receipt.get("public_response_binding") or {})
    workspace_binding = dict(formal.workspace_response_binding)
    if (
        len(events) != int(formal.event_receipt.get("event_count") or -1)
        or any(item.get("session_id") != formal.session_id for item in events)
        or any(
            not isinstance(cursor, int) or isinstance(cursor, bool)
            for cursor in cursors
        )
        or cursors != sorted(set(cursors))
        or canonical_digest(events)
        != formal.event_receipt.get("event_stream_digest")
        or event_binding.get("route")
        != f"/v3/sessions/{formal.session_id}/events?replay=1&after_cursor=0"
        or workspace_binding.get("route")
        != f"/v3/sessions/{formal.session_id}/workspace"
    ):
        raise LiveProductPathError(
            "public_final_snapshot_invalid",
            "fault final public workspace/event responses are not closed preimages",
        )
    workspace_payload = {
        "schema_id": "aox_public_final_workspace_snapshot@1",
        "session_id": formal.session_id,
        "workspace": dict(formal.workspace),
        "workspace_digest": canonical_digest(formal.workspace),
        "response_binding": workspace_binding,
    }
    event_payload = {
        "schema_id": "aox_public_final_event_replay@1",
        "session_id": formal.session_id,
        "replay": True,
        "after_cursor": 0,
        "events": events,
        "event_count": len(events),
        "last_cursor": max(cursors, default=0),
        "event_stream_digest": canonical_digest(events),
        "response_binding": event_binding,
    }
    workspace_bytes = canonical_json_bytes(workspace_payload) + b"\n"
    event_bytes = canonical_json_bytes(event_payload) + b"\n"
    workspace_artifact_id = (
        f"art_public_final_workspace_{_safe_id(context.roots.attempt_id)}"
    )
    event_artifact_id = (
        f"art_public_final_events_{_safe_id(context.roots.attempt_id)}"
    )
    workspace_path = "formal/attestation/public-final-workspace.json"
    event_path = "formal/attestation/public-final-event-replay.json"
    _write_sealed_bytes(context.roots.artifact_root, workspace_path, workspace_bytes)
    _write_sealed_bytes(context.roots.artifact_root, event_path, event_bytes)
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": workspace_artifact_id,
                "relative_path": workspace_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {
                    "producer": "aox_public_final_workspace_snapshot@1"
                },
            },
            {
                "artifact_id": event_artifact_id,
                "relative_path": event_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {"producer": "aox_public_final_event_replay@1"},
            },
        ]
    )
    product_path.update(
        {
            "public_final_workspace_digest": canonical_digest(formal.workspace),
            "public_final_workspace_response_binding": workspace_binding,
            "public_final_event_stream_digest": canonical_digest(events),
            "public_final_event_last_cursor": max(cursors, default=0),
            "public_final_event_response_binding": event_binding,
            "public_final_scientific_evidence_digest": canonical_digest(
                dict(formal.workspace.get("scientific_evidence") or {})
            ),
            "public_final_workspace_artifact_id": workspace_artifact_id,
            "public_final_workspace_artifact_digest": _sha256(workspace_bytes),
            "public_final_event_replay_artifact_id": event_artifact_id,
            "public_final_event_replay_artifact_digest": _sha256(event_bytes),
        }
    )
    evidence["product_path"] = product_path


def _copy_fault_target(
    context: AttemptRunContext,
    *,
    artifact: SessionArtifactRecord,
    fault: FaultInjectionReceipt,
    derivation_operation_id: str,
) -> CatalogArtifactCopy:
    source = Path(artifact.storage_uri)
    if not source.is_file() or source.is_symlink():
        raise LiveProductPathError(
            "fault_target_blob_invalid",
            "controlled fault target is not a sealed regular-file blob",
        )
    resolved_source = source.resolve()
    if context.roots.blob_root.resolve() not in resolved_source.parents:
        raise LiveProductPathError(
            "fault_target_blob_unbound",
            "controlled fault target is outside the attempt-scoped blob root",
        )
    if artifact.relative_path != fault.target_relative_path:
        raise LiveProductPathError(
            "fault_target_catalog_path_mismatch",
            "controlled fault receipt does not match the catalog target path",
        )
    target_contract_path = "aox_hmm/AOX_ref21.fasta"
    if artifact.relative_path != target_contract_path:
        raise LiveProductPathError(
            "fault_target_catalog_path_mismatch",
            "controlled fault target is not the exact AOX reference-set deliverable",
        )
    expected_kind, expected_format = AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACTS[
        target_contract_path
    ]
    raw_format = dict(artifact.metadata or {}).get("format")
    artifact_format = raw_format if isinstance(raw_format, str) else ""
    if artifact.kind.value != expected_kind or artifact_format != expected_format:
        raise LiveProductPathError(
            "final_deliverable_artifact_contract_mismatch",
            "controlled fault target has the wrong catalog kind or format",
            details={
                "path": artifact.relative_path,
                "expected_kind": expected_kind,
                "actual_kind": artifact.kind.value,
                "expected_format": expected_format,
                "actual_format": artifact_format,
            },
        )
    content = source.read_bytes()
    if (
        not content
        or fault.byte_offset < 0
        or fault.byte_offset >= len(content)
        or _sha256(content) != fault.after_digest
        or str(
            dict(artifact.metadata or {}).get("content_digest")
            or dict(artifact.metadata or {}).get("sealed_digest")
            or ""
        )
        != fault.before_digest
    ):
        raise LiveProductPathError(
            "fault_target_digest_mismatch",
            "controlled fault target bytes do not match the before/after receipt",
        )
    restored = bytearray(content)
    restored[fault.byte_offset] ^= 1
    if _sha256(bytes(restored)) != fault.before_digest:
        raise LiveProductPathError(
            "fault_target_not_single_bit_flip",
            "controlled fault target cannot be restored by the declared one-bit flip",
        )
    relative_path = (
        f"formal/fault/{_safe_id(artifact.artifact_id)}/"
        f"{_safe_id(PurePosixPath(artifact.relative_path).name)}"
    )
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    return CatalogArtifactCopy(
        record={
            "artifact_id": artifact.artifact_id,
            "relative_path": relative_path,
            "scope": "formal",
            "origin": "operation",
            "kind": artifact.kind.value,
            "format": artifact_format,
            "deliverable_path": artifact.relative_path,
            "deliverable_artifact_contract_id": (
                AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
            ),
            "provenance": {
                "operation_id": derivation_operation_id,
                "catalog_artifact_id": artifact.artifact_id,
                "catalog_relative_path": artifact.relative_path,
                "controlled_fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                "derivation_id": fault.derivation_id,
                "deliverable_path": artifact.relative_path,
                "deliverable_artifact_contract_id": (
                    AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
                ),
            },
        },
        content=content,
        content_digest=fault.after_digest,
    )


def _fault_operation_input_refs(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    target_artifact_id: str,
    before_digest: str,
    copies: dict[str, CatalogArtifactCopy],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for artifact_id, declared_digest in zip(
        operation.input_artifact_ids,
        operation.input_artifact_digests,
        strict=True,
    ):
        if artifact_id == target_artifact_id:
            if declared_digest != before_digest:
                raise LiveProductPathError(
                    "fault_failed_input_digest_mismatch",
                    "failed controlled operation was not bound to the pre-fault digest",
                )
            refs.append({"artifact_id": artifact_id, "content_digest": declared_digest})
            continue
        artifact = _require_artifact(artifacts, artifact_id)
        copied = _copy_catalog_artifact(
            context,
            artifact,
            scope="formal",
            origin="input",
            provenance={"operation_input_for": operation.operation_id},
            cache=copies,
        )
        if copied.content_digest != declared_digest:
            raise LiveProductPathError(
                "fault_controlled_input_digest_mismatch",
                "unmodified fault-path input differs from its S12 digest",
            )
        refs.append({"artifact_id": artifact_id, "content_digest": declared_digest})
    return refs


def _fault_task_receipts(
    *,
    tasks: tuple[object, ...],
    agents: tuple[object, ...],
    documents: tuple[object, ...],
    consumer_task_id: str,
) -> list[dict[str, object]]:
    agents_by_id = {
        str(getattr(agent, "agent_id")): str(getattr(agent, "role", ""))
        for agent in agents
    }
    finish_documents: dict[str, list[object]] = {}
    for document in documents:
        if getattr(document, "document_kind", None) != "task_finish":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        task_id = str(payload.get("task_id") or "")
        if task_id:
            finish_documents.setdefault(task_id, []).append(document)
    receipts: list[dict[str, object]] = []
    for task in tasks:
        task_id = str(getattr(task, "task_id", ""))
        status = str(getattr(getattr(task, "status", None), "value", ""))
        assigned_ref = str(getattr(task, "assigned_ref", "") or "")
        role = agents_by_id.get(assigned_ref, "")
        matches = finish_documents.get(task_id, [])
        if (
            not task_id
            or status not in _TERMINAL_TASK_STATUSES
            or role not in {"researcher", "executor", "reporter"}
            or len(matches) != 1
        ):
            raise LiveProductPathError(
                "fault_task_business_exit_invalid",
                "fault closure requires one explicit task.finish for every observed formal task",
                details={"task_id": task_id or "missing"},
            )
        finish = matches[0]
        finish_payload = dict(getattr(finish, "payload", None) or {})
        if finish_payload.get("status") != status or not str(
            finish_payload.get("finished_by") or ""
        ):
            raise LiveProductPathError(
                "fault_task_business_exit_invalid",
                "fault task state does not match its durable task.finish receipt",
                details={"task_id": task_id},
            )
        if task_id == consumer_task_id and (
            role != "executor" or status not in {"failed", "blocked", "cancelled"}
        ):
            raise LiveProductPathError(
                "fault_execution_task_not_failed",
                "the task owning the failed MAFFT consumer must exit failed, blocked, or cancelled",
                details={"task_id": task_id, "status": status, "role": role},
            )
        if role == "reporter" and status == "completed":
            raise LiveProductPathError(
                "fault_reporting_task_completed",
                "a reporting task cannot complete after the required-chain fault",
                details={"task_id": task_id},
            )
        receipts.append(
            {
                "task_id": task_id,
                "role": role,
                "kind": str(getattr(task, "kind", "")),
                "status": status,
                "business_exit": "agent_explicit",
                "assigned_ref": assigned_ref,
                "lane_id": getattr(task, "lane_id", None),
                "finish_ref": str(getattr(finish, "document_id", "")),
                "finish_payload_digest": canonical_digest(finish_payload),
                "finished_by": str(finish_payload["finished_by"]),
                "evidence_refs": [
                    str(item) for item in finish_payload.get("evidence_refs") or []
                ],
            }
        )
    if not receipts or consumer_task_id not in {
        str(item["task_id"]) for item in receipts
    }:
        raise LiveProductPathError(
            "fault_execution_task_missing",
            "fault closure does not contain the task that owned the failed MAFFT consumer",
        )
    return sorted(receipts, key=lambda item: str(item["task_id"]))


def _fault_negative_state_receipt(
    *,
    session_id: str,
    fault: FaultInjectionReceipt,
    task_receipts: list[dict[str, object]],
    reports: tuple[object, ...],
    drafts: tuple[object, ...],
    conversation: tuple[object, ...],
    durable_events: tuple[object, ...],
    operations: tuple[ControlledOperation, ...],
    artifacts: tuple[SessionArtifactRecord, ...],
) -> dict[str, object]:
    report_states = sorted(
        (
            {
                "report_id": str(getattr(report, "report_id", "")),
                "task_id": getattr(report, "task_id", None),
                "status": str(getattr(getattr(report, "status", None), "value", "")),
                "artifact_id": getattr(report, "artifact_id", None),
            }
            for report in reports
        ),
        key=lambda item: str(item["report_id"]),
    )
    draft_states = sorted(
        (
            {
                "draft_id": str(getattr(draft, "draft_id", "")),
                "task_id": getattr(draft, "task_id", None),
                "status": str(getattr(getattr(draft, "status", None), "value", "")),
                "content_ref": getattr(draft, "content_ref", None),
                "published_report_id": getattr(draft, "published_report_id", None),
            }
            for draft in drafts
        ),
        key=lambda item: str(item["draft_id"]),
    )
    if any(item["status"] in {"ready", "published"} for item in report_states) or any(
        item["status"] in {"ready", "published"} or item["published_report_id"]
        for item in draft_states
    ):
        raise LiveProductPathError(
            "fault_success_report_present",
            "fault closure found an actual ready/published report or published draft",
        )
    conversation_receipts = [
        {
            "message_id": str(getattr(message, "message_id", "")),
            "role": str(getattr(message, "role", "")),
            "content_digest": _sha256(
                str(getattr(message, "content", "")).encode("utf-8")
            ),
        }
        for message in conversation
    ]
    explicit_success_markers = (
        "local live cutover go",
        "cutover-eligible report",
        "aox/hmm completed successfully",
        "published final report",
    )
    success_claim_message_ids = [
        str(getattr(message, "message_id", ""))
        for message in conversation
        if str(getattr(message, "role", "")) == "assistant"
        and any(
            marker in str(getattr(message, "content", "")).casefold()
            for marker in explicit_success_markers
        )
    ]
    if success_claim_message_ids:
        raise LiveProductPathError(
            "fault_assistant_success_claim_present",
            "fault conversation contains an explicit structured success declaration",
        )
    assistant_messages = [
        message
        for message in conversation
        if str(getattr(message, "role", "")) == "assistant"
    ]
    final_assistant = assistant_messages[-1] if assistant_messages else None
    final_assistant_content = (
        "" if final_assistant is None else str(getattr(final_assistant, "content", ""))
    )
    if final_assistant is not None and not all(
        marker in final_assistant_content
        for marker in (
            "failure_code=artifact_blob_digest_mismatch",
            "status=failed",
        )
    ):
        raise LiveProductPathError(
            "fault_final_assistant_not_failure_bound",
            "the final fault-path assistant message must bind the exact terminal failure code",
        )
    event_receipts: list[dict[str, object]] = []
    previous_cursor = 0
    for event in durable_events:
        cursor = getattr(event, "cursor", None)
        if (
            not isinstance(cursor, int)
            or isinstance(cursor, bool)
            or cursor <= previous_cursor
        ):
            raise LiveProductPathError(
                "fault_durable_event_cursor_invalid",
                "fault durable-event closure is not strictly ordered",
            )
        previous_cursor = cursor
        event_receipts.append(
            {
                "event_id": str(getattr(event, "event_id", "")),
                "cursor": cursor,
                "event_type": str(getattr(event, "event_type", "")),
                "actor_ref": getattr(event, "actor_ref", None),
                "command_id": getattr(event, "command_id", None),
                "payload_digest": canonical_digest(
                    dict(getattr(event, "payload", None) or {})
                ),
            }
        )
    if not event_receipts:
        raise LiveProductPathError(
            "fault_durable_event_closure_missing",
            "fault closure lacks the durable event history for the formal session",
        )
    consumers = [
        operation
        for operation in operations
        if fault.target_artifact_id in operation.input_artifact_ids
    ]
    consumer_states = sorted(
        (
            {
                "operation_id": operation.operation_id,
                "task_id": operation.task_id,
                "sdk_module": operation.sdk_module,
                "function_name": operation.function_name,
                "selected_backend": operation.selected_backend,
                "status": operation.status.value,
                "failure_code": operation.error_code,
                "operation_identity_digest": operation.operation_digest,
            }
            for operation in consumers
        ),
        key=lambda item: str(item["operation_id"]),
    )
    successful_alternate_consumer_ids = [
        str(item["operation_id"])
        for item in consumer_states
        if item["status"] == "completed"
    ]
    if (
        not consumer_states
        or successful_alternate_consumer_ids
        or any(
            item["status"] not in _FAILED_OPERATION_STATUSES for item in consumer_states
        )
    ):
        raise LiveProductPathError(
            "fault_alternate_consumer_not_closed",
            "every consumer of the mutated derived artifact must terminate unsuccessfully",
        )
    observed_final_paths = sorted(
        {
            artifact.relative_path
            for artifact in artifacts
            if artifact.relative_path in S15_AOX_HMM_FIXED_DELIVERABLES
        }
    )
    allowed_prefault_paths = {
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
    }
    post_fault_paths = sorted(set(observed_final_paths) - allowed_prefault_paths)
    if post_fault_paths:
        raise LiveProductPathError(
            "fault_final_deliverable_present",
            "required-chain failure produced downstream final deliverables",
            details={"paths": post_fault_paths},
        )
    return {
        "schema_id": FAULT_NEGATIVE_CLOSURE_SCHEMA_ID,
        "session_id": session_id,
        "target_artifact_id": fault.target_artifact_id,
        "terminal_failure_operation_id": fault.terminal_failure_operation_id,
        "task_receipts": task_receipts,
        "report_states": report_states,
        "draft_states": draft_states,
        "conversation_receipts": conversation_receipts,
        "success_claim_message_ids": success_claim_message_ids,
        "final_assistant_failure_message_id": (
            None
            if final_assistant is None
            else str(getattr(final_assistant, "message_id", ""))
        ),
        "final_assistant_failure_code": (
            None if final_assistant is None else "artifact_blob_digest_mismatch"
        ),
        "final_assistant_failure_status": (
            None if final_assistant is None else "failed"
        ),
        "durable_event_receipts": event_receipts,
        "consumer_states": consumer_states,
        "successful_alternate_consumer_ids": successful_alternate_consumer_ids,
        "observed_prefault_deliverable_paths": observed_final_paths,
        "post_fault_final_deliverable_paths": post_fault_paths,
        "complete_final_deliverable_set_present": (
            S15_AOX_HMM_FIXED_DELIVERABLES
            <= {artifact.relative_path for artifact in artifacts}
        ),
    }


def _collect_fault_evidence(
    context: AttemptRunContext,
    *,
    provider: SQLiteRepositoryProvider,
    api_receipts: tuple[PublicApiReceipt, ...],
    health: Mapping[str, object],
    probe: SessionDriveResult,
    formal: SessionDriveResult,
    fault: FaultInjectionReceipt,
    ledger_path: Path,
    micu_record_ids_before: set[int],
    effective_config: Mapping[str, object],
) -> dict[str, Any]:
    probe_attestation = _collect_probe_attestation(
        context,
        provider=provider,
        probe=probe,
    )
    with provider.read() as scope:
        repositories = scope.repositories
        operation_records = tuple(
            repositories.controlled_operations.list_by_session(formal.session_id)
        )
        operations = {
            operation.operation_id: operation for operation in operation_records
        }
        approvals = {
            approval.approval_id: approval
            for approval in repositories.approvals.list_by_session(formal.session_id)
        }
        artifact_records = tuple(
            repositories.artifacts.list_by_session(formal.session_id)
        )
        artifacts = {artifact.artifact_id: artifact for artifact in artifact_records}
        sandbox_runs = {
            run.sandbox_run_id: run
            for run in repositories.sandbox_runs.list_by_session(formal.session_id)
        }
        tasks = tuple(repositories.tasks.list_by_session(formal.session_id))
        agents = tuple(repositories.agents.list_by_session(formal.session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(formal.session_id)
        )
        reports = tuple(repositories.reports.list_by_session(formal.session_id))
        drafts = tuple(repositories.report_drafts.list_by_session(formal.session_id))
        conversation = build_conversation_projection(repositories, formal.session_id)
        durable_events = _durable_events_by_session(repositories, formal.session_id)
    formal_hpc_workspace_ids = _require_attempt_hpc_workspace_binding(
        context,
        operation_records,
    )
    probe_hpc_workspace_id = str(
        dict(probe_attestation.probe.get("isolation") or {}).get("hpc_workspace_id")
        or ""
    )
    source_operation = operations.get(fault.source_operation_id)
    failed_operation = operations.get(fault.terminal_failure_operation_id)
    source_artifact = artifacts.get(fault.source_artifact_id)
    target_artifact = artifacts.get(fault.target_artifact_id)
    sandbox_run = (
        None
        if failed_operation is None
        else sandbox_runs.get(str(failed_operation.sandbox_run_id or ""))
    )
    if (
        source_operation is None
        or failed_operation is None
        or source_artifact is None
        or target_artifact is None
        or sandbox_run is None
        or source_operation.operation_id == failed_operation.operation_id
        or source_operation.status.value != "completed"
        or source_operation.selected_backend != "provider_http"
        or source_operation.sdk_module != "bio"
        or source_operation.function_name != "ncbi_fetch_proteins"
        or failed_operation.status.value not in _FAILED_OPERATION_STATUSES
        or failed_operation.error_code != "artifact_blob_digest_mismatch"
        or failed_operation.sdk_module != "bio_tools"
        or failed_operation.function_name != "mafft"
        or failed_operation.selected_backend != "hpc"
        or failed_operation.toolchain_id
        != AOX_TOOLCHAIN_RUNTIME_CONTRACTS["mafft"]["toolchain_id"]
        or fault.source_artifact_id
        not in _operation_output_artifact_ids(source_operation)
        or fault.target_artifact_id not in failed_operation.input_artifact_ids
        or target_artifact.run_id != failed_operation.sandbox_run_id
        or fault.derivation_id != aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
        or fault.derivation_contract_digest
        != aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        or fault.derivation_implementation_digest
        != aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        or fault.consumer_tool_id != "bio_tools.mafft"
    ):
        raise LiveProductPathError(
            "controlled_fault_operation_receipt_invalid",
            "controlled byte flip does not bind exact NCBI source, reference derivation, and failed MAFFT consumer",
        )
    copies: dict[str, CatalogArtifactCopy] = {}
    source_inputs = _fault_operation_input_refs(
        context,
        source_operation,
        artifacts=artifacts,
        target_artifact_id=fault.target_artifact_id,
        before_digest=fault.before_digest,
        copies=copies,
    )
    source_parameters = _provider_request_parameters(
        context,
        source_operation,
        artifacts=artifacts,
    )
    source_outputs, source_response_digest = _provider_output_copies(
        context,
        source_operation,
        artifacts=artifacts,
        copies=copies,
    )
    source_copy = next(
        (
            copy
            for copy in source_outputs
            if str(copy.record["artifact_id"]) == fault.source_artifact_id
        ),
        None,
    )
    if (
        source_copy is None
        or source_copy.content_digest != fault.source_artifact_digest
    ):
        raise LiveProductPathError(
            "controlled_fault_source_artifact_invalid",
            "fault source does not resolve to the sealed NCBI exact-14 FASTA",
        )
    source_record = operation_evidence_record(
        source_operation,
        scope="formal",
        inputs=source_inputs,
        outputs=[_artifact_ref(copy) for copy in source_outputs],
        parameters=source_parameters,
    )
    derivation_inputs = [_artifact_ref(source_copy)]
    derivation_outputs = [
        {
            "artifact_id": fault.target_artifact_id,
            "content_digest": fault.before_digest,
        }
    ]
    derivation_record = _sandbox_calculation_record(
        run=sandbox_run,
        role="fault_hmm_reference_set_selection",
        calculation_id=fault.derivation_id,
        calculation_contract_digest=fault.derivation_contract_digest,
        calculation_implementation_digest=fault.derivation_implementation_digest,
        parameters={
            "source_artifact_id": fault.source_artifact_id,
            "source_digest": fault.source_artifact_digest,
            "expected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
        },
        inputs=derivation_inputs,
        outputs=derivation_outputs,
    )
    target_copy = _copy_fault_target(
        context,
        artifact=target_artifact,
        fault=fault,
        derivation_operation_id=str(derivation_record["operation_id"]),
    )
    for prefault_artifact in artifact_records:
        if (
            prefault_artifact.artifact_id != fault.target_artifact_id
            and prefault_artifact.relative_path
            in {
                "aox_hmm/AOX_ref21.fasta",
                "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
            }
            and prefault_artifact.artifact_id not in copies
        ):
            _copy_catalog_artifact(
                context,
                prefault_artifact,
                scope="formal",
                origin="attestation",
                provenance={
                    "producer": FAULT_NEGATIVE_CLOSURE_SCHEMA_ID,
                    "state": "allowed_prefault_deliverable",
                },
                cache=copies,
            )
    consumers = [
        operation
        for operation in operation_records
        if fault.target_artifact_id in operation.input_artifact_ids
    ]
    consumer_records: list[dict[str, object]] = []
    for consumer in consumers:
        consumer_inputs = _fault_operation_input_refs(
            context,
            consumer,
            artifacts=artifacts,
            target_artifact_id=fault.target_artifact_id,
            before_digest=fault.before_digest,
            copies=copies,
        )
        consumer_records.append(
            operation_evidence_record(
                consumer,
                scope="formal",
                inputs=consumer_inputs,
                outputs=[],
            )
        )
    failed_record = next(
        (
            record
            for record in consumer_records
            if record["operation_id"] == failed_operation.operation_id
        ),
        None,
    )
    if failed_record is None:
        raise LiveProductPathError(
            "controlled_fault_consumer_missing",
            "failed MAFFT consumer is absent from the target consumer closure",
        )
    invocation_id = _operation_backend_run_id(source_record)
    consumer_task_id = str(failed_operation.task_id or "")
    task_records = _fault_task_receipts(
        tasks=tasks,
        agents=agents,
        documents=documents,
        consumer_task_id=consumer_task_id,
    )
    task_records = _bind_delegation_workflow_receipts(
        context,
        task_receipts=task_records,
        documents=documents,
    )
    source_snapshot_artifact_id = str(
        getattr(sandbox_run, "source_snapshot_artifact_id", "") or ""
    )
    source_snapshot_digest = str(getattr(sandbox_run, "source_tree_digest", "") or "")
    _copy_catalog_artifact(
        context,
        _require_artifact(artifacts, source_snapshot_artifact_id),
        scope="formal",
        origin="sandbox_run",
        provenance={
            "producer": "sandbox_source_snapshot",
            "sandbox_run_id": str(getattr(sandbox_run, "sandbox_run_id")),
            "source_snapshot_digest": source_snapshot_digest,
        },
        cache=copies,
    )
    negative_closure = _fault_negative_state_receipt(
        session_id=formal.session_id,
        fault=fault,
        task_receipts=task_records,
        reports=reports,
        drafts=drafts,
        conversation=conversation,
        durable_events=durable_events,
        operations=operation_records,
        artifacts=artifact_records,
    )
    execution_config = dict(effective_config.get("execution") or {})
    runner_expectations = dict(
        execution_config.get("aox_runner_contract_expectations") or {}
    )
    runner_contracts = dict(runner_expectations.get("contracts") or {})
    mafft_runner_contract = dict(runner_contracts.get("bio_tools.mafft") or {})
    expected_mafft_contract = AOX_TOOLCHAIN_RUNTIME_CONTRACTS["mafft"]
    if (
        set(mafft_runner_contract)
        != {"adapter_id", "command_template_id", "runner_contract_digest"}
        or mafft_runner_contract.get("adapter_id")
        != expected_mafft_contract["adapter_id"]
        or mafft_runner_contract.get("command_template_id")
        != expected_mafft_contract["command_template_id"]
        or _SHA256_DIGEST_PATTERN.fullmatch(
            str(mafft_runner_contract.get("runner_contract_digest") or "")
        )
        is None
    ):
        raise LiveProductPathError(
            "fault_runner_contract_expectation_invalid",
            "fault evidence lacks the exact effective-config MAFFT runner contract",
        )
    consumer_runner_contract_expectation = {
        "tool_id": "bio_tools.mafft",
        **mafft_runner_contract,
    }
    negative_closure["consumer_runner_contract_expectation"] = (
        consumer_runner_contract_expectation
    )
    blocker_payload = {
        "schema_id": LIVE_BLOCKER_SCHEMA_ID,
        "runner_schema_id": LIVE_RUNNER_SCHEMA_ID,
        "attempt_id": context.roots.attempt_id,
        "attempt_kind": "fault",
        "observed_at": datetime.now(UTC).isoformat(),
        "failure_code": "artifact_blob_digest_mismatch",
        "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "target_artifact_id": fault.target_artifact_id,
        "source_artifact_id": fault.source_artifact_id,
        "source_operation_id": source_operation.operation_id,
        "derivation_operation_id": derivation_record["operation_id"],
        "derivation_id": fault.derivation_id,
        "terminal_failure_operation_id": failed_operation.operation_id,
        "health": dict(health),
        "formal": formal.safe_summary(),
        "negative_state_closure": negative_closure,
    }
    closure_content = canonical_json_bytes(blocker_payload) + b"\n"
    closure_artifact_id = f"art_fault_closure_{_safe_id(context.roots.attempt_id)}"
    closure_path = "formal/fault/negative-state-closure.json"
    _write_sealed_bytes(context.roots.artifact_root, closure_path, closure_content)
    evidence_relative_path = str(target_copy.record["relative_path"])
    fault_payload = {
        "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "target_artifact_id": fault.target_artifact_id,
        "source_artifact_id": fault.source_artifact_id,
        "source_artifact_digest": fault.source_artifact_digest,
        "relative_path": evidence_relative_path,
        "byte_offset": fault.byte_offset,
        "before_digest": fault.before_digest,
        "after_digest": fault.after_digest,
        "source_operation_id": source_operation.operation_id,
        "derivation_operation_id": derivation_record["operation_id"],
        "derivation_id": fault.derivation_id,
        "derivation_contract_digest": fault.derivation_contract_digest,
        "derivation_implementation_digest": fault.derivation_implementation_digest,
        "consumer_tool_id": fault.consumer_tool_id,
        "consumer_runner_contract_expectation": (consumer_runner_contract_expectation),
        "terminal_failure_operation_id": failed_operation.operation_id,
        "failure_code": "artifact_blob_digest_mismatch",
        "negative_state_closure_artifact_id": closure_artifact_id,
        "negative_state_closure_digest": _sha256(closure_content),
        "reached_target_seam": True,
        "expected_failure_observed": True,
    }
    micu_receipts = _new_micu_attempt_receipts(
        ledger_path,
        before_ids=micu_record_ids_before,
    )
    micu_models = {receipt.model for receipt in micu_receipts}
    if len(micu_models) != 1:
        raise LiveProductPathError(
            "fault_micu_attempt_model_ambiguous",
            "fault attempt MICU charges do not close over exactly one model",
        )
    product_path = _product_path_failure_receipt(
        context,
        formal=formal,
        api_receipts=api_receipts,
    )
    product_path.update(
        {
            "participant_roles": sorted(
                {
                    str(getattr(agent, "role"))
                    for agent in agents
                    if str(getattr(agent, "role", "")) != "master"
                }
            ),
            "runtime_config_digest": str(context.identity["config_digest"]),
            "micu_scenario": "aox_blank_world_cutover",
            "micu_model": next(iter(micu_models)),
            "micu_invocation_ids": [receipt.invocation_id for receipt in micu_receipts],
            "negative_state_closure_artifact_id": closure_artifact_id,
            "hpc_workspace_binding": {
                "schema_id": AOX_HPC_WORKSPACE_BINDING_CONTRACT_ID,
                "label": context.roots.hpc_workspace_label,
                "workspace_ids": sorted(
                    formal_hpc_workspace_ids | {probe_hpc_workspace_id}
                ),
            },
        }
    )
    assistant_messages = [
        message
        for message in conversation
        if str(getattr(message, "role", "")) == "assistant"
    ]
    final_message = assistant_messages[-1] if assistant_messages else None
    return {
        "provider_identities": [
            {
                "provider_record_id": f"provider_record_fault_{_safe_id(source_operation.operation_id)}",
                "provider": "ncbi",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": invocation_id,
                "operation_id": source_operation.operation_id,
                "cache_hit": False,
                "request_digest": source_operation.params_digest,
                "response_digest": source_response_digest,
                "artifact_ids": [
                    str(copy.record["artifact_id"]) for copy in source_outputs
                ],
                "source_ref_ids": [],
            }
        ],
        "engine_invocations": [],
        "toolchain_identities": [],
        "known_positive_probe": probe_attestation.probe,
        "product_path": product_path,
        "approvals": [
            *probe_attestation.approvals,
            _approval_record(source_operation, approvals),
            *(_approval_record(consumer, approvals) for consumer in consumers),
        ],
        "operations": [
            *probe_attestation.operations,
            source_record,
            derivation_record,
            *consumer_records,
        ],
        "tasks": task_records,
        "artifacts": [
            *probe_attestation.artifacts,
            *(copy.record for copy in copies.values()),
            target_copy.record,
            {
                "artifact_id": closure_artifact_id,
                "relative_path": closure_path,
                "scope": "formal",
                "origin": "report",
                "kind": "failure_evidence",
                "provenance": {
                    "producer": FAULT_NEGATIVE_CLOSURE_SCHEMA_ID,
                    "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                },
            },
        ],
        "report": {
            "report_id": f"report_fault_closure_{_safe_id(context.roots.attempt_id)}",
            "status": "failed_evidence",
            "cutover_eligible": False,
            "content_artifact_id": closure_artifact_id,
            "content_digest": _sha256(closure_content),
            "artifact_ids": [closure_artifact_id, fault.target_artifact_id],
            "source_ref_ids": [],
            "claim_source_links": [],
        },
        "final_answer": {
            "message_id": "" if final_message is None else final_message.message_id,
            "content": "" if final_message is None else final_message.content,
        },
        "scientific_checks": {},
        "warnings": [],
        "degradations": ["controlled_fault_injection"],
        "scientific_outcome": {
            "status": "failed",
            "failure_code": "artifact_blob_digest_mismatch",
            "cutover_eligible": False,
        },
        "fault_injection": fault_payload,
    }


def _collect_probe_attestation(
    context: AttemptRunContext,
    *,
    provider: SQLiteRepositoryProvider,
    probe: SessionDriveResult,
) -> ProbeAttestation:
    with provider.read() as scope:
        repositories = scope.repositories
        operations = tuple(
            repositories.controlled_operations.list_by_session(probe.session_id)
        )
        approvals = {
            approval.approval_id: approval
            for approval in repositories.approvals.list_by_session(probe.session_id)
        }
        artifact_map = {
            artifact.artifact_id: artifact
            for artifact in repositories.artifacts.list_by_session(probe.session_id)
        }
        sandbox_runs = {
            run.sandbox_run_id: run
            for run in repositories.sandbox_runs.list_by_session(probe.session_id)
        }
        tasks = tuple(repositories.tasks.list_by_session(probe.session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(probe.session_id)
        )
    _require_attempt_hpc_workspace_binding(context, operations)

    operation_specs = (
        ("ncbi_fetch", "bio", "ncbi_fetch_proteins"),
        ("reference_alignment", "bio_tools", "mafft"),
        ("hmm_build", "bio_tools", "hmmbuild"),
        ("uniprot_fetch", "bio", "uniprot_fetch"),
        ("candidate_cluster", "bio_tools", "cdhit"),
        ("candidate_alignment", "bio_tools", "hmmalign"),
    )
    operation_by_role: dict[str, ControlledOperation] = {}
    for role, sdk_module, function_name in operation_specs:
        matches = [
            operation
            for operation in operations
            if operation.sdk_module == sdk_module
            and operation.function_name == function_name
        ]
        if len(matches) != 1:
            raise LiveProductPathError(
                "probe_operation_receipt_ambiguous",
                "known-positive probe requires exactly one operation for every fixed role",
                details={
                    "role": role,
                    "sdk_method": f"{sdk_module}.{function_name}",
                    "operation_count": len(matches),
                },
            )
        if matches[0].status.value != "completed":
            raise LiveProductPathError(
                "probe_operation_not_completed",
                "an attempted known-positive probe operation did not complete",
                details={"role": role, "status": matches[0].status.value},
            )
        operation_by_role[role] = matches[0]
    expected_operation_ids = {
        operation.operation_id for operation in operation_by_role.values()
    }
    if (
        len(operations) != len(operation_specs)
        or {operation.operation_id for operation in operations}
        != expected_operation_ids
    ):
        raise LiveProductPathError(
            "probe_operation_surface_invalid",
            "known-positive probe must contain exactly two provider and four HPC operations",
            details={"observed_operation_count": len(operations)},
        )

    task_ids = {str(operation.task_id or "") for operation in operations}
    sandbox_run_ids = {str(operation.sandbox_run_id or "") for operation in operations}
    sandbox_workspace_ids = {
        str(operation.sandbox_workspace_id or "") for operation in operations
    }
    source_snapshot_ids = {
        str(operation.source_snapshot_artifact_id or "") for operation in operations
    }
    source_snapshot_digests = {
        str(operation.source_snapshot_digest or "") for operation in operations
    }
    hpc_workspace_ids = {
        str(operation.hpc_workspace_id or "")
        for role, operation in operation_by_role.items()
        if role
        in {
            "reference_alignment",
            "hmm_build",
            "candidate_cluster",
            "candidate_alignment",
        }
    }
    if any(
        len(values) != 1 or "" in values
        for values in (
            task_ids,
            sandbox_run_ids,
            sandbox_workspace_ids,
            source_snapshot_ids,
            source_snapshot_digests,
            hpc_workspace_ids,
        )
    ):
        raise LiveProductPathError(
            "probe_isolation_scope_invalid",
            "probe operations must share one task, sandbox run/workspace, source snapshot, and HPC workspace",
        )
    task_id = next(iter(task_ids))
    matching_tasks = [task for task in tasks if str(task.task_id) == task_id]
    finish_documents = [
        document
        for document in documents
        if document.document_kind == "task_finish"
        and str(dict(document.payload or {}).get("task_id") or "") == task_id
    ]
    if (
        len(tasks) != 1
        or len(matching_tasks) != 1
        or matching_tasks[0].status.value != "completed"
        or len(finish_documents) != 1
        or dict(finish_documents[0].payload or {}).get("status") != "completed"
    ):
        raise LiveProductPathError(
            "probe_task_finish_invalid",
            "known-positive probe requires one explicitly finished execution task",
        )
    sandbox_run_id = next(iter(sandbox_run_ids))
    sandbox_run = sandbox_runs.get(sandbox_run_id)
    if (
        sandbox_run is None
        or sandbox_run.status.value != "completed"
        or str(sandbox_run.source_snapshot_artifact_id or "")
        != next(iter(source_snapshot_ids))
        or str(sandbox_run.source_tree_digest or "")
        != next(iter(source_snapshot_digests))
    ):
        raise LiveProductPathError(
            "probe_sandbox_receipt_invalid",
            "probe operations do not resolve to one completed persistent sandbox run",
        )

    copies: dict[str, CatalogArtifactCopy] = {}
    output_copies: dict[str, list[CatalogArtifactCopy]] = {}
    operation_records: list[dict[str, object]] = []
    provider_parameters: dict[str, dict[str, object]] = {}
    provider_response_digests: dict[str, str] = {}
    for role, _, _ in operation_specs:
        operation = operation_by_role[role]
        inputs = _declared_operation_input_refs(
            context,
            operation,
            artifacts=artifact_map,
            copies=copies,
            scope="probe",
        )
        if role in {"ncbi_fetch", "uniprot_fetch"}:
            parameters = _provider_request_parameters(
                context,
                operation,
                artifacts=artifact_map,
            )
            selected_outputs, response_digest = _provider_output_copies(
                context,
                operation,
                artifacts=artifact_map,
                copies=copies,
                scope="probe",
            )
            provider_parameters[role] = parameters
            provider_response_digests[role] = response_digest
        else:
            parameters = None
            selected_outputs = _tool_output_copies(
                context,
                operation,
                artifacts=artifact_map,
                copies=copies,
                scope="probe",
            )
        output_copies[role] = selected_outputs
        operation_records.append(
            operation_evidence_record(
                operation,
                scope="probe",
                inputs=inputs,
                outputs=[_artifact_ref(copy) for copy in selected_outputs],
                parameters=parameters,
            )
        )

    source_snapshot = _copy_catalog_artifact(
        context,
        _require_artifact(artifact_map, next(iter(source_snapshot_ids))),
        scope="probe",
        origin="sandbox_run",
        provenance={
            "probe_id": KNOWN_POSITIVE_PROBE_ID,
            "producer": "sandbox_source_snapshot",
            "sandbox_run_id": sandbox_run_id,
            "source_snapshot_digest": next(iter(source_snapshot_digests)),
        },
        cache=copies,
    )
    ncbi_raw = _copy_with_name(
        output_copies["ncbi_fetch"],
        names={"ncbi_efetch.response.json"},
        identity="probe_ncbi_raw_response",
    )
    ncbi_fasta = _copy_with_name(
        output_copies["ncbi_fetch"],
        names={"proteins.fasta"},
        identity="probe_ncbi_fasta",
    )
    uniprot_raw = _copy_with_name(
        output_copies["uniprot_fetch"],
        names={"pages.json"},
        identity="probe_uniprot_raw_response",
    )
    uniprot_fasta = _copy_with_name(
        output_copies["uniprot_fetch"],
        names={"sequences.fasta"},
        identity="probe_uniprot_fasta",
    )
    reference_alignment = _copy_with_name(
        output_copies["reference_alignment"],
        names={"alignment.fasta"},
        identity="probe_reference_alignment",
    )
    hmm_model = _copy_with_name(
        output_copies["hmm_build"],
        names={"model.hmm"},
        identity="probe_hmm_model",
    )
    clustered_fasta = _copy_with_name(
        output_copies["candidate_cluster"],
        names={"clustered.fasta"},
        identity="probe_clustered_fasta",
    )
    cluster_membership = _copy_with_name(
        output_copies["candidate_cluster"],
        names={"clusters.csv"},
        identity="probe_cluster_membership",
    )
    candidate_alignment = _copy_with_name(
        output_copies["candidate_alignment"],
        names={"aligned.fasta"},
        identity="probe_candidate_alignment",
    )

    expected_provider_accessions = {
        "ncbi_fetch": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
        "uniprot_fetch": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
    }
    for role, expected_accessions in expected_provider_accessions.items():
        observed_accessions = [
            str(value).strip().upper()
            for value in provider_parameters[role].get("accessions") or []
        ]
        if observed_accessions != expected_accessions:
            raise LiveProductPathError(
                "probe_provider_identity_mismatch",
                "known-positive provider request does not use the fixed globin identities",
                details={
                    "role": role,
                    "expected": expected_accessions,
                    "actual": observed_accessions,
                },
            )

    operation_record_by_role = {
        role: record for (role, _, _), record in zip(operation_specs, operation_records)
    }

    def require_exact_inputs(role: str, expected: list[CatalogArtifactCopy]) -> None:
        actual = {
            str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
            for ref in operation_record_by_role[role].get("inputs") or []
            if isinstance(ref, dict)
        }
        wanted = {
            str(copy.record["artifact_id"]): copy.content_digest for copy in expected
        }
        if actual != wanted:
            raise LiveProductPathError(
                "probe_artifact_lineage_invalid",
                "known-positive probe operation inputs do not match the fixed provider/tool DAG",
                details={"role": role},
            )

    require_exact_inputs("reference_alignment", [ncbi_fasta])
    require_exact_inputs("hmm_build", [reference_alignment])
    require_exact_inputs("candidate_cluster", [uniprot_fasta])
    require_exact_inputs("candidate_alignment", [hmm_model, clustered_fasta])

    try:
        ncbi_sequences = aox_similarity.parse_candidate_fasta(ncbi_fasta.content)
        uniprot_sequences = aox_similarity.parse_candidate_fasta(uniprot_fasta.content)
        clustered_sequences = aox_similarity.parse_candidate_fasta(
            clustered_fasta.content
        )
        membership = aox_similarity.parse_cdhit_membership_csv(
            cluster_membership.content
        )
    except ValueError as exc:
        raise LiveProductPathError(
            "probe_scientific_artifact_invalid",
            "known-positive provider or CD-HIT output is not offline-parseable",
        ) from exc
    ncbi_ids = [record.sequence_id for record in ncbi_sequences.records]
    uniprot_ids = [record.sequence_id for record in uniprot_sequences.records]
    clustered_ids = [record.sequence_id for record in clustered_sequences.records]
    ncbi_sequence_digests = sorted(
        record.sequence_digest for record in ncbi_sequences.records
    )
    uniprot_sequence_digests = sorted(
        record.sequence_digest for record in uniprot_sequences.records
    )
    membership_member_ids = sorted(row.member_id for row in membership.rows)
    if (
        ncbi_ids != list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)
        or uniprot_ids != list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)
        or sorted(clustered_ids) != sorted(uniprot_ids)
        or membership_member_ids != sorted(uniprot_ids)
        or len(membership.rows) != 2
        or not all(row.is_representative for row in membership.rows)
        or ncbi_sequence_digests != uniprot_sequence_digests
        or not hmm_model.content.startswith(b"HMMER")
    ):
        raise LiveProductPathError(
            "probe_known_positive_result_invalid",
            "sealed globin identities do not close through both providers and the real toolchain",
        )

    def aligned_sequence_ids(content: bytes) -> list[str]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LiveProductPathError(
                "probe_alignment_not_utf8",
                "known-positive alignment output is not UTF-8",
            ) from exc
        return [
            line[1:].strip().split(maxsplit=1)[0]
            for line in text.splitlines()
            if line.startswith(">")
        ]

    if aligned_sequence_ids(reference_alignment.content) != list(
        KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS
    ) or aligned_sequence_ids(candidate_alignment.content) != list(
        KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS
    ):
        raise LiveProductPathError(
            "probe_alignment_identity_mismatch",
            "MAFFT/HMMalign outputs do not preserve the fixed globin member identities",
        )
    cdhit_metadata = dict(
        artifact_map[str(clustered_fasta.record["artifact_id"])].metadata or {}
    )
    cdhit_tool_inputs = dict(cdhit_metadata.get("tool_inputs") or {})
    if (
        float(cdhit_tool_inputs.get("identity") or 0.0) != 1.0
        or cdhit_tool_inputs.get("mode") != "protein"
    ):
        raise LiveProductPathError(
            "probe_cdhit_parameters_invalid",
            "known-positive CD-HIT operation must use identity 1.0 and protein mode",
        )

    provider_receipts: list[dict[str, object]] = []
    for role, provider_name, raw_copy, fasta_copy in (
        ("ncbi_fetch", "ncbi", ncbi_raw, ncbi_fasta),
        ("uniprot_fetch", "uniprot", uniprot_raw, uniprot_fasta),
    ):
        receipt = _controlled_provider_receipt(
            provider_name=provider_name,
            operation=operation_by_role[role],
            operation_record=operation_record_by_role[role],
            output_copies=output_copies[role],
            response_digest=provider_response_digests[role],
        )
        receipt.update(
            {
                "raw_response_artifact_id": str(raw_copy.record["artifact_id"]),
                "parsed_fasta_artifact_id": str(fasta_copy.record["artifact_id"]),
            }
        )
        provider_receipts.append(receipt)
    toolchain_receipts: list[dict[str, object]] = []
    for role, tool_name in (
        ("reference_alignment", "mafft"),
        ("hmm_build", "hmmbuild"),
        ("candidate_cluster", "cd-hit"),
        ("candidate_alignment", "hmmalign"),
    ):
        receipt = _toolchain_receipt(
            tool_name=tool_name,
            operation=operation_by_role[role],
            operation_record=operation_record_by_role[role],
        )
        receipt["artifact_ids"] = [
            str(copy.record["artifact_id"]) for copy in output_copies[role]
        ]
        if role == "candidate_cluster":
            receipt["parameters"] = {"identity": 1.0, "mode": "protein"}
        toolchain_receipts.append(receipt)

    approval_records = [
        _approval_record(operation_by_role[role], approvals)
        for role, _, _ in operation_specs
    ]
    if len({record["approval_id"] for record in approval_records}) != 6:
        raise LiveProductPathError(
            "probe_approval_receipt_missing",
            "known-positive probe requires one distinct approval per controlled operation",
        )
    provider_by_name = {
        str(receipt["provider"]): receipt for receipt in provider_receipts
    }
    toolchain_by_tool = {
        str(receipt["tool"]): receipt for receipt in toolchain_receipts
    }
    artifact_roles = {
        "source_snapshot": str(source_snapshot.record["artifact_id"]),
        "ncbi_raw_response": str(ncbi_raw.record["artifact_id"]),
        "ncbi_fasta": str(ncbi_fasta.record["artifact_id"]),
        "mafft_alignment": str(reference_alignment.record["artifact_id"]),
        "hmm_model": str(hmm_model.record["artifact_id"]),
        "uniprot_raw_response": str(uniprot_raw.record["artifact_id"]),
        "uniprot_fasta": str(uniprot_fasta.record["artifact_id"]),
        "cdhit_clustered_fasta": str(clustered_fasta.record["artifact_id"]),
        "cdhit_membership": str(cluster_membership.record["artifact_id"]),
        "hmmalign_alignment": str(candidate_alignment.record["artifact_id"]),
    }
    operation_roles = {
        role: operation.operation_id for role, operation in operation_by_role.items()
    }
    probe_payload = {
        "probe_id": KNOWN_POSITIVE_PROBE_ID,
        "status": "passed",
        "bounded": True,
        "formal_data_isolated": True,
        "artifact_ids": sorted(copies),
        "operation_roles": operation_roles,
        "artifact_roles": artifact_roles,
        "isolation": {
            "schema_id": "aox_known_positive_probe_isolation@1",
            "session_id": probe.session_id,
            "task_id": task_id,
            "task_finish_ref": str(finish_documents[0].document_id),
            "sandbox_run_id": sandbox_run_id,
            "sandbox_workspace_id": next(iter(sandbox_workspace_ids)),
            "source_snapshot_artifact_id": str(source_snapshot.record["artifact_id"]),
            "source_snapshot_digest": next(iter(source_snapshot_digests)),
            "source_snapshot_artifact_digest": source_snapshot.content_digest,
            "hpc_workspace_id": next(iter(hpc_workspace_ids)),
            "controlled_operation_count": 6,
        },
        "known_positive_identity": {
            "ncbi_accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "uniprot_accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
            "cross_provider_sequence_digest": canonical_digest(ncbi_sequence_digests),
        },
        "checks": [
            {
                "check_id": "ncbi_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["ncbi"]["provider_record_id"],
            },
            {
                "check_id": "uniprot_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["uniprot"]["provider_record_id"],
            },
            *(
                {
                    "check_id": f"hpc_{tool_name.replace('-', '')}",
                    "category": "hpc",
                    "status": "passed",
                    "receipt_id": toolchain_by_tool[tool_name]["toolchain_record_id"],
                }
                for tool_name in ("mafft", "hmmbuild", "cd-hit", "hmmalign")
            ),
        ],
        "provider_receipts": provider_receipts,
        "toolchain_receipts": toolchain_receipts,
    }
    return ProbeAttestation(
        probe=probe_payload,
        approvals=tuple(approval_records),
        operations=tuple(operation_records),
        artifacts=tuple(copy.record for copy in copies.values()),
    )


def _failed_probe_payload(probe: SessionDriveResult | None) -> dict[str, object]:
    state = "failed" if probe is None else probe.state
    return {
        "probe_id": KNOWN_POSITIVE_PROBE_ID,
        "status": "failed",
        "failure_code": (
            "probe_not_started" if probe is None else "probe_attestation_unavailable"
        ),
        "bounded": True,
        "formal_data_isolated": True,
        "artifact_ids": [],
        "checks": [
            *(
                {
                    "check_id": check_id,
                    "category": "provider",
                    "status": "failed",
                }
                for check_id in (
                    "ncbi_globin_pair",
                    "uniprot_globin_pair",
                )
            ),
            *(
                {
                    "check_id": check_id,
                    "category": "hpc",
                    "status": "failed",
                }
                for check_id in (
                    "hpc_mafft",
                    "hpc_hmmbuild",
                    "hpc_cdhit",
                    "hpc_hmmalign",
                )
            ),
        ],
        "observed_state": state,
    }


def _product_path_failure_receipt(
    context: AttemptRunContext,
    *,
    formal: SessionDriveResult | None,
    api_receipts: tuple[PublicApiReceipt, ...],
) -> dict[str, object]:
    entry_messages = []
    assistant_messages = []
    if formal is not None:
        conversation = list(formal.workspace.get("conversation") or [])
        entry_messages = [
            dict(item)
            for item in conversation
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        assistant_messages = [
            dict(item)
            for item in conversation
            if isinstance(item, dict) and item.get("role") == "assistant"
        ]
    return {
        "entry_message_count": len(entry_messages),
        "canonical_api_only": True,
        "cache_hit": False,
        "participant_roles": [],
        "session_id": None if formal is None else formal.session_id,
        "entry_message_id": None
        if not entry_messages
        else entry_messages[0].get("message_id"),
        "entry_message_digest": (
            ""
            if not entry_messages
            else _sha256(
                str(entry_messages[0].get("content") or "").encode("utf-8")
            )
        ),
        "final_master_response_id": None
        if not assistant_messages
        else assistant_messages[-1].get("message_id"),
        "public_api_receipt_digest": canonical_digest(
            [item.to_dict() for item in api_receipts]
        ),
        "launch_receipt": {
            "root_identity": context.roots.proof["root_identity"],
            "hpc_workspace_label": context.roots.hpc_workspace_label,
            "sqlite_initialized_fresh": context.roots.sqlite_path.is_file(),
            "artifact_root_bound": context.roots.artifact_root.is_dir(),
            "blob_root_bound": context.roots.blob_root.is_dir(),
            "sandbox_root_bound": context.roots.sandbox_root.is_dir(),
        },
    }


def _safe_health(health: Mapping[str, object]) -> dict[str, object]:
    components = health.get("components")
    statuses = {
        str(name): str(dict(value).get("status") or "unknown")
        for name, value in (components.items() if isinstance(components, dict) else [])
        if isinstance(value, dict)
    }
    sandbox_component = (
        dict(components.get("sandbox") or {}) if isinstance(components, dict) else {}
    )
    sandbox_details = dict(sandbox_component.get("details") or {})
    sandbox_runtime_identity = {
        key: value
        for key, value in {
            "image_digest": sandbox_details.get("image_digest"),
            "pipeline_sdk_digest": sandbox_details.get("pipeline_sdk_digest"),
            "runtime_identity_digest": sandbox_details.get("runtime_identity_digest"),
            "sandbox_protocol_version": sandbox_details.get("sandbox_protocol_version"),
        }.items()
        if isinstance(value, str) and value
    }
    return {
        "schema_version": health.get("schema_version"),
        "status": health.get("status"),
        "deployment_profile": health.get("deployment_profile"),
        "storage_profile": health.get("storage_profile"),
        "component_statuses": statuses,
        "sandbox_runtime_identity": sandbox_runtime_identity,
    }


def _write_sealed_bytes(root: Path, relative_path: str, content: bytes) -> None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise LiveProductPathError(
            "collector_artifact_path_invalid",
            "collector artifact path is not a safe relative path",
        )
    target = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_root not in resolved_target.parents or target.exists():
        raise LiveProductPathError(
            "collector_artifact_append_only",
            "collector artifact target escapes its root or already exists",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def _safe_message(error: LiveProductPathError) -> str:
    return str(error).split(": ", 1)[-1][:500]


def _emit_operator_record(payload: Mapping[str, object]) -> None:
    print(
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


def _safe_id(value: str) -> str:
    return _SAFE_ID.sub("_", value).strip("._-")[:100] or "attempt"


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = [
    "LIVE_RUNNER_SCHEMA_ID",
    "LiveAoxAttemptRunner",
    "LiveProductPathError",
    "PublicApiReceipt",
    "SessionDriveResult",
    "controlled_operation_identity_material",
    "operation_evidence_record",
]
