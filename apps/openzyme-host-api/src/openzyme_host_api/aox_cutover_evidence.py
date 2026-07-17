from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Protocol
from uuid import uuid4

from openzyme_runtime import LIVE_MICU_TOKEN_HARD_LIMIT
from openzyme_runtime import summarize_live_micu_token_ledger


ATTEMPT_BUNDLE_SCHEMA_ID = "aox_blank_world_attempt_bundle@1"
CAMPAIGN_DECISION_SCHEMA_ID = "aox_blank_world_campaign_decision@1"
KNOWN_POSITIVE_PROBE_SCHEMA_ID = "aox_known_positive_probe@2"
KNOWN_POSITIVE_PROBE_ID = "independent_globin_provider_hpc_probe"
KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS = ("NP_000509.1", "NP_000549.1")
KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS = ("P68871", "P69905")
FAULT_ARTIFACT_BYTE_FLIP_ID = "sealed_provider_artifact_byte_flip@1"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTEMPT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"^(?:authorization|cookie|password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|storage_uri|source_uri|host_path|remote_path)$",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/-]+|\bsk-(?:ant-)?[A-Za-z0-9_-]{12,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"\b(?:api[_-]?key|client[_-]?secret|password|secret|access[_-]?token)"
    r"\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
_HOST_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'=:,(])(?:/(?:home|root|tmp|var|run|opt|mnt|Users)/|"
    r"[A-Za-z]:\\|\\\\[A-Za-z0-9_.-]+\\)",
)
_PRIVATE_URL_PATTERN = re.compile(
    r"https?://(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|"
    r"\[?::1\]?)(?::\d+)?(?:[/\s]|$)",
    re.IGNORECASE,
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


@dataclass(frozen=True, slots=True)
class BlankWorldRoots:
    attempt_id: str
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
class AttemptRunContext:
    roots: BlankWorldRoots
    identity: dict[str, str]
    ledger_before: dict[str, Any]
    attempt_number: int


@dataclass(frozen=True, slots=True)
class AttemptRunRecord:
    attempt_id: str
    attempt_kind: str
    bundle_path: Path
    artifact_root: Path
    bundle_digest: str
    verification: VerificationResult


class AttemptRunner(Protocol):
    def __call__(self, context: AttemptRunContext) -> dict[str, Any]: ...


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


def create_blank_world_roots(
    campaign_root: Path,
    *,
    attempt_kind: str,
    allowed_prerequisites: Mapping[str, object],
    attempt_id: str | None = None,
) -> BlankWorldRoots:
    if attempt_kind not in {"positive", "fault"}:
        raise CutoverEvidenceError(
            "attempt_kind_invalid",
            "blank-world attempt kind must be positive or fault",
            details={"attempt_kind": attempt_kind},
        )
    identifier = attempt_id or f"{attempt_kind}-{uuid4().hex}"
    if _ATTEMPT_ID_PATTERN.fullmatch(identifier) is None:
        raise CutoverEvidenceError(
            "attempt_id_invalid",
            "attempt id must be a short path-safe identifier",
            details={"attempt_id": identifier},
        )
    prerequisites = dict(allowed_prerequisites)
    unknown_prerequisites = sorted(
        str(key) for key in set(prerequisites) - _ALLOWED_PREREQUISITE_KEYS
    )
    if unknown_prerequisites:
        raise CutoverEvidenceError(
            "allowed_prerequisite_field_forbidden",
            "blank-world prerequisites must use the closed identity-only schema",
            details={"fields": unknown_prerequisites},
        )
    _assert_public_safe(prerequisites, identity="allowed_prerequisites")
    base = campaign_root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    attempt_root = base / identifier
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
            "every cutover attempt must use a newly created root",
            details={"attempt_id": identifier},
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
    hpc_workspace_label = f"aox-cutover-{uuid4().hex}"
    prerequisite_digest = canonical_digest(prerequisites)
    root_identity = canonical_digest(
        {
            "attempt_id": identifier,
            "attempt_kind": attempt_kind,
            "nonce": uuid4().hex,
            "root_names": root_names,
            "hpc_workspace_label": hpc_workspace_label,
        }
    )
    proof = {
        "schema_id": "aox_blank_world_root_proof@1",
        "attempt_id": identifier,
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
        attempt_id=identifier,
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


def build_attempt_bundle(
    *,
    attempt_id: str,
    attempt_kind: str,
    identity: Mapping[str, object],
    clean_world: Mapping[str, object],
    ledger_before: Mapping[str, object],
    ledger_after: Mapping[str, object],
    artifact_root: Path,
    evidence: Mapping[str, object],
    sealed_at: str | None = None,
) -> dict[str, Any]:
    normalized_identity = _normalize_identity(identity)
    before = dict(ledger_before)
    after = dict(ledger_after)
    _validate_ledger_transition(before, after)
    payload: dict[str, Any] = {
        "schema_id": ATTEMPT_BUNDLE_SCHEMA_ID,
        "attempt_id": attempt_id,
        "attempt_kind": attempt_kind,
        "sealed_at": sealed_at or datetime.now(UTC).isoformat(),
        "identity": {
            **normalized_identity,
            "identity_digest": canonical_digest(normalized_identity),
        },
        "clean_world": dict(clean_world),
        "micu_ledger": {"before": before, "after": after},
        "provider_identities": _list_of_dicts(evidence, "provider_identities"),
        "engine_invocations": _list_of_dicts(evidence, "engine_invocations"),
        "toolchain_identities": _list_of_dicts(evidence, "toolchain_identities"),
        "known_positive_probe": dict(evidence.get("known_positive_probe") or {}),
        "product_path": dict(evidence.get("product_path") or {}),
        "approvals": _list_of_dicts(evidence, "approvals"),
        "operations": _list_of_dicts(evidence, "operations"),
        "tasks": _list_of_dicts(evidence, "tasks"),
        "artifacts": _list_of_dicts(evidence, "artifacts"),
        "report": dict(evidence.get("report") or {}),
        "final_answer": dict(evidence.get("final_answer") or {}),
        "scientific_checks": dict(evidence.get("scientific_checks") or {}),
        "warnings": list(evidence.get("warnings") or []),
        "degradations": list(evidence.get("degradations") or []),
        "scientific_outcome": dict(evidence.get("scientific_outcome") or {}),
        "fault_injection": (
            None
            if evidence.get("fault_injection") is None
            else dict(evidence.get("fault_injection") or {})
        ),
    }
    _normalize_artifacts(payload, artifact_root=artifact_root)
    _normalize_record_digests(payload)
    _validate_attempt_semantics(payload, artifact_root=artifact_root)
    _assert_public_safe(payload, identity="attempt_bundle")
    return payload


def seal_attempt_bundle(payload: Mapping[str, object], destination: Path) -> str:
    normalized = dict(payload)
    bundle_digest = canonical_digest(normalized)
    envelope = {"payload": normalized, "bundle_digest": bundle_digest}
    _write_append_only_bytes(
        destination,
        canonical_json_bytes(envelope) + b"\n",
        error_code="attempt_bundle_append_only",
        error_message="attempt bundle already exists and cannot be overwritten",
    )
    return bundle_digest


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


def verify_attempt_bundle(
    bundle_path: Path,
    *,
    artifact_root: Path,
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
            _verify_similarity(
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
            )
            _verify_fault_injection(
                payload,
                artifact_root=artifact_root,
                artifact_map=artifact_map,
                issues=issues,
            )
            _validate_attempt_semantics(payload, artifact_root=artifact_root)
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


def inject_artifact_byte_flip(
    artifact_root: Path,
    *,
    relative_path: str,
    byte_offset: int = 0,
) -> dict[str, Any]:
    target = _resolve_artifact_path(artifact_root, relative_path)
    content = target.read_bytes()
    if not content:
        raise CutoverEvidenceError(
            "fault_target_empty",
            "byte-flip fault target must be a non-empty sealed artifact",
            details={"relative_path": relative_path},
        )
    if byte_offset < 0 or byte_offset >= len(content):
        raise CutoverEvidenceError(
            "fault_offset_invalid",
            "byte-flip offset is outside the target artifact",
            details={"byte_offset": byte_offset, "size_bytes": len(content)},
        )
    before_digest = _sha256(content)
    mutated = bytearray(content)
    mutated[byte_offset] ^= 1
    target.chmod(0o600)
    target.write_bytes(bytes(mutated))
    target.chmod(0o444)
    return {
        "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "relative_path": relative_path,
        "byte_offset": byte_offset,
        "before_digest": before_digest,
        "after_digest": _sha256(bytes(mutated)),
        "reached_target_seam": True,
    }


def _report_publish_receipt_is_valid(report: Mapping[str, Any]) -> bool:
    report_id = str(report.get("report_id") or "")
    session_id = str(report.get("session_id") or "")
    task_id = str(report.get("task_id") or "")
    lane_id = str(report.get("lane_id") or "")
    draft_id = str(report.get("draft_id") or "")
    content_ref = str(report.get("content_ref") or "")
    content_digest = str(report.get("content_digest") or "")
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
        and report.get("status") == "ready"
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
        and product_report.get("report_id") == report_id
        and product_report.get("session_id") == session_id
        and product_report.get("task_id") == task_id
        and product_report.get("lane_id") == lane_id
        and product_report.get("invocation_id") in {None, ""}
        and product_report.get("run_id") in {None, ""}
        and product_report.get("artifact_id") in {None, ""}
        and product_report.get("status") == "ready"
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


@dataclass(slots=True)
class AoxCutoverCampaign:
    campaign_root: Path
    identity: Mapping[str, object]
    ledger_path: Path
    positive_runner: AttemptRunner
    fault_runner: AttemptRunner
    allowed_prerequisites: Mapping[str, object]

    def run(self) -> tuple[tuple[AttemptRunRecord, ...], dict[str, Any]]:
        records: list[AttemptRunRecord] = []
        try:
            for number, kind in enumerate(("positive", "positive", "fault"), start=1):
                record, cutover_eligible = self._run_attempt(
                    number=number,
                    kind=kind,
                )
                records.append(record)
                if kind == "positive" and (
                    not record.verification.passed or not cutover_eligible
                ):
                    break
        except Exception as exc:
            decision = _campaign_driver_failure_decision(
                records,
                failure=exc,
                campaign_root=self.campaign_root,
            )
            seal_campaign_decision(
                decision,
                self.campaign_root / "campaign-decision.json",
            )
            return tuple(records), decision
        decision = evaluate_campaign(records)
        decision_path = self.campaign_root / "campaign-decision.json"
        seal_campaign_decision(decision, decision_path)
        return tuple(records), decision

    def _run_attempt(
        self,
        *,
        number: int,
        kind: str,
    ) -> tuple[AttemptRunRecord, bool]:
        roots = create_blank_world_roots(
            self.campaign_root,
            attempt_kind=kind,
            allowed_prerequisites=self.allowed_prerequisites,
        )
        before = safe_micu_ledger_snapshot(self.ledger_path)
        runner = self.positive_runner if kind == "positive" else self.fault_runner
        context = AttemptRunContext(
            roots=roots,
            identity=_normalize_identity(self.identity),
            ledger_before=before,
            attempt_number=number,
        )
        try:
            evidence = runner(context)
        except Exception as exc:
            evidence = _campaign_runner_failure_evidence(
                roots.artifact_root,
                failure_type=type(exc).__name__,
                attempt_kind=kind,
            )
        after = safe_micu_ledger_snapshot(self.ledger_path)
        payload = build_attempt_bundle(
            attempt_id=roots.attempt_id,
            attempt_kind=kind,
            identity=self.identity,
            clean_world=roots.proof,
            ledger_before=before,
            ledger_after=after,
            artifact_root=roots.artifact_root,
            evidence=evidence,
        )
        bundle_path = roots.evidence_root / "attempt-bundle.json"
        bundle_digest = seal_attempt_bundle(payload, bundle_path)
        verification = verify_attempt_bundle(
            bundle_path,
            artifact_root=roots.artifact_root,
        )
        return (
            AttemptRunRecord(
                attempt_id=roots.attempt_id,
                attempt_kind=kind,
                bundle_path=bundle_path,
                artifact_root=roots.artifact_root,
                bundle_digest=bundle_digest,
                verification=verification,
            ),
            dict(payload.get("scientific_outcome") or {}).get("cutover_eligible")
            is True,
        )


def _campaign_driver_failure_decision(
    records: Sequence[AttemptRunRecord],
    *,
    failure: Exception,
    campaign_root: Path,
) -> dict[str, Any]:
    failure_code = (
        failure.code
        if isinstance(failure, CutoverEvidenceError)
        else "campaign_driver_failed"
    )
    failure_payload = {
        "schema_id": "aox_campaign_driver_failure@1",
        "failure_code": failure_code,
        "failure_type": type(failure).__name__,
        "completed_attempt_digests": [record.bundle_digest for record in records],
    }
    failure_digest = canonical_digest(failure_payload)
    _write_append_only_bytes(
        campaign_root / "campaign-driver-failure.json",
        canonical_json_bytes(
            {"payload": failure_payload, "failure_digest": failure_digest}
        )
        + b"\n",
        error_code="campaign_driver_failure_append_only",
        error_message="campaign driver failure evidence already exists",
    )
    decision_payload = {
        "schema_id": CAMPAIGN_DECISION_SCHEMA_ID,
        "decided_at": datetime.now(UTC).isoformat(),
        "decision": "NO-GO",
        "attempt_digests": [record.bundle_digest for record in records],
        "attempt_ids": [record.attempt_id for record in records],
        "blocker": {
            "code": failure_code,
            "identity": "campaign.driver",
            "message": "campaign driver failed before a qualifying attempt could be sealed",
        },
        "driver_failure_digest": failure_digest,
    }
    return {
        **decision_payload,
        "decision_digest": canonical_digest(decision_payload),
    }


def _campaign_runner_failure_evidence(
    artifact_root: Path,
    *,
    failure_type: str,
    attempt_kind: str,
) -> dict[str, Any]:
    relative_path = "formal/campaign-driver-failure.json"
    content = (
        canonical_json_bytes(
            {
                "schema_id": "aox_campaign_driver_failure@1",
                "status": "failed",
                "failure_type": failure_type,
            }
        )
        + b"\n"
    )
    target = _resolve_artifact_path(artifact_root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    content_digest = _sha256(content)
    return {
        "provider_identities": [],
        "engine_invocations": [],
        "toolchain_identities": [],
        "known_positive_probe": {
            "probe_id": "probe_not_completed",
            "status": "failed",
            "bounded": True,
            "formal_data_isolated": True,
            "artifact_ids": [],
            "checks": [
                {
                    "check_id": "required_provider_probe",
                    "category": "provider",
                    "status": "failed",
                },
                {
                    "check_id": "required_hpc_probe",
                    "category": "hpc",
                    "status": "failed",
                },
            ],
        },
        "product_path": {
            "entry_message_count": 0,
            "canonical_api_only": True,
            "participant_roles": [],
        },
        "approvals": [],
        "operations": [],
        "tasks": [],
        "artifacts": [
            {
                "artifact_id": "art_campaign_driver_failure",
                "relative_path": relative_path,
                "scope": "formal",
                "origin": "report",
                "kind": "failure_evidence",
                "provenance": {
                    "producer": "aox_cutover_campaign",
                    "failure_type": failure_type,
                },
            }
        ],
        "report": {
            "report_id": "report_campaign_driver_failure",
            "status": "failed_evidence",
            "cutover_eligible": False,
            "content_artifact_id": "art_campaign_driver_failure",
            "content_digest": content_digest,
            "artifact_ids": ["art_campaign_driver_failure"],
            "source_ref_ids": [],
            "claim_source_links": [],
        },
        "final_answer": {
            "message_id": "campaign_driver_failure",
            "content": "The blank-world attempt failed before product-path completion.",
        },
        "scientific_checks": {},
        "warnings": [],
        "degradations": ["required_product_path_unavailable"],
        "scientific_outcome": {
            "status": "failed",
            "failure_code": "campaign_runner_failed",
            "failure_type": failure_type,
            "cutover_eligible": False,
        },
        "fault_injection": (
            None
            if attempt_kind == "positive"
            else {
                "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                "reached_target_seam": False,
                "expected_failure_observed": False,
                "failure_code": "campaign_runner_failed",
            }
        ),
    }


def _normalize_identity(identity: Mapping[str, object]) -> dict[str, str]:
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
    if (
        not normalized["workflow_ref"].startswith("workflow:")
        or "#sha256:" not in normalized["workflow_ref"]
    ):
        raise CutoverEvidenceError(
            "campaign_workflow_ref_invalid",
            "campaign workflow ref must be a full digest-pinned selection ref",
            details={"identity": "identity.workflow_ref"},
        )
    return normalized


def _normalize_artifacts(payload: dict[str, Any], *, artifact_root: Path) -> None:
    artifacts = list(payload["artifacts"])
    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(artifacts):
        record = dict(raw)
        artifact_id = str(record.get("artifact_id") or "").strip()
        relative_path = str(record.get("relative_path") or "").strip()
        if not artifact_id or artifact_id in seen_ids:
            raise CutoverEvidenceError(
                "artifact_identity_invalid",
                "artifact ids must be non-empty and unique",
                details={"identity": f"artifacts[{index}]"},
            )
        seen_ids.add(artifact_id)
        path = _resolve_artifact_path(artifact_root, relative_path)
        if not path.is_file() or path.is_symlink():
            raise CutoverEvidenceError(
                "artifact_file_invalid",
                "attempt bundle artifacts must be sealed regular files",
                details={"identity": artifact_id},
            )
        provenance = dict(record.get("provenance") or {})
        record["artifact_id"] = artifact_id
        record["relative_path"] = PurePosixPath(relative_path).as_posix()
        record["scope"] = str(record.get("scope") or "formal")
        record["origin"] = str(record.get("origin") or "operation")
        record["size_bytes"] = path.stat().st_size
        record["content_digest"] = _sha256(path.read_bytes())
        record["provenance"] = provenance
        record["provenance_digest"] = canonical_digest(provenance)
        normalized.append(record)
    payload["artifacts"] = sorted(normalized, key=lambda item: item["artifact_id"])


def _normalize_record_digests(payload: dict[str, Any]) -> None:
    for collection, identity_key, digest_key in (
        ("provider_identities", "provider_record_id", "record_digest"),
        ("engine_invocations", "invocation_id", "record_digest"),
        ("toolchain_identities", "toolchain_record_id", "record_digest"),
        ("approvals", "approval_id", "record_digest"),
        ("operations", "operation_id", "record_digest"),
        ("tasks", "task_id", "record_digest"),
    ):
        records = []
        seen_identities: set[str] = set()
        for raw in payload[collection]:
            record = dict(raw)
            record_identity = str(record.get(identity_key) or "").strip()
            if not record_identity or record_identity in seen_identities:
                raise CutoverEvidenceError(
                    "record_identity_invalid",
                    f"{collection} records require unique non-empty {identity_key}",
                    details={"identity": collection},
                )
            seen_identities.add(record_identity)
            digest_payload = {
                key: value for key, value in record.items() if key != digest_key
            }
            record[digest_key] = canonical_digest(digest_payload)
            records.append(record)
        payload[collection] = sorted(records, key=lambda item: str(item[identity_key]))
    probe = dict(payload["known_positive_probe"])
    probe.setdefault("schema_id", KNOWN_POSITIVE_PROBE_SCHEMA_ID)
    probe["record_digest"] = canonical_digest(
        {key: value for key, value in probe.items() if key != "record_digest"}
    )
    payload["known_positive_probe"] = probe
    report = dict(payload["report"])
    report["record_digest"] = canonical_digest(
        {key: value for key, value in report.items() if key != "record_digest"}
    )
    payload["report"] = report
    final_answer = dict(payload["final_answer"])
    content = str(final_answer.get("content") or "")
    final_answer["content_digest"] = _sha256(content.encode("utf-8"))
    payload["final_answer"] = final_answer


def _validate_clean_world_proof(payload: Mapping[str, Any]) -> None:
    clean_world = dict(payload.get("clean_world") or {})
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
    prerequisites = dict(clean_world.get("allowed_prerequisites") or {})
    unknown_prerequisites = sorted(
        str(key) for key in set(prerequisites) - _ALLOWED_PREREQUISITE_KEYS
    )
    if unknown_prerequisites:
        raise CutoverEvidenceError(
            "blank_world_prerequisite_invalid",
            "clean-root proof contains an unauthorized prerequisite field",
            details={"identity": "clean_world.allowed_prerequisites"},
        )
    if (
        clean_world.get("schema_id") != "aox_blank_world_root_proof@1"
        or clean_world.get("attempt_id") != payload.get("attempt_id")
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
    return (
        artifact.get("content_digest") == response_digest
        or _provider_response_bytes_contain_digest(content, response_digest)
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
        "derived_accession_artifact_id": payload.get(
            "derived_accession_artifact_id"
        ),
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
        and payload.get("reason")
        in {"no_hmmer_hits", "no_filtered_hmmer_accessions"}
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
            str(item)
            for item in dependency.get("upstream_response_artifact_ids") or []
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
                or raw_envelope.get("schema_id")
                != "provider_raw_http_response_set@1"
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
                str(ref.get("artifact_id") or ""): str(
                    ref.get("content_digest") or ""
                )
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
                result_refs[artifact_id] = str(
                    artifact.get("content_digest") or ""
                )
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
            == "canonical_empty_cluster_membership@1"
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
                hit.raw_page_digest in raw_response_body_digests
                for hit in result.hits
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
            and derivation_operation.get("canonical_ref_kind")
            == "sandbox_calculation"
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
            _DIGEST_PATTERN.fullmatch(str(provider.get("request_digest") or ""))
            is None
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
            or provider.get("status")
            not in {"completed", "empty", "upstream_empty"}
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
        if (
            invocation.get("engine_name") != "research_tool"
            or invocation.get("status") != "succeeded"
            or not str(invocation.get("task_id") or "")
            or not str(invocation.get("lane_id") or "")
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
    product_path = dict(payload.get("product_path") or {})
    expected_task_ids = {
        role: role_to_ids[role][0] for role in sorted(_REQUIRED_TASK_ROLES)
    }
    launch_receipt = dict(product_path.get("launch_receipt") or {})
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


def _validate_known_positive_probe(
    payload: Mapping[str, Any], *, artifact_root: Path
) -> None:
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
        str(provider.get("provider_record_id") or "")
        in formal_provider_record_ids
        or str(provider.get("invocation_id") or "")
        in formal_provider_invocation_ids
        or str(provider.get("operation_id") or "")
        in formal_provider_operation_ids
        for provider in provider_receipts
    ) or any(
        str(toolchain.get("toolchain_record_id") or "")
        in formal_toolchain_record_ids
        or str(toolchain.get("job_id") or "") in formal_toolchain_job_ids
        or str(toolchain.get("operation_id") or "")
        in formal_toolchain_operation_ids
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
            or raw_payload.get("schema_id")
            != "provider_raw_http_response_set@1"
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
            or _DIGEST_PATTERN.fullmatch(
                str(provider.get("request_digest") or "")
            )
            is None
            or provider.get("request_digest") != operation.get("params_digest")
            or _DIGEST_PATTERN.fullmatch(
                str(provider.get("response_digest") or "")
            )
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
            or _DIGEST_PATTERN.fullmatch(
                str(toolchain.get("image_digest") or "")
            )
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
            dict(
                role_operations[role].get("operation_identity_material") or {}
            ).get("hpc_workspace_id")
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
        or common_sandbox_run_ids
        != {str(isolation.get("sandbox_run_id") or "")}
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
            and sorted(row.member_id for row in membership.rows)
            == sorted(uniprot_ids)
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
                "uniprot_accessions": list(
                    KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS
                ),
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
    payload: Mapping[str, Any], *, artifact_root: Path
) -> None:
    if payload.get("schema_id") != ATTEMPT_BUNDLE_SCHEMA_ID:
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
    _validate_clean_world_proof(payload)
    micu = dict(payload.get("micu_ledger") or {})
    _validate_ledger_transition(
        dict(micu.get("before") or {}),
        dict(micu.get("after") or {}),
    )
    artifacts = [dict(item) for item in payload.get("artifacts") or []]
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
        or any(item.get("status") not in {"passed", "failed"} for item in checks)
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
    if any(
        task.get("status") not in {"completed", "failed", "cancelled"}
        or task.get("business_exit")
        not in {"agent_explicit", "documented_mechanical_transition"}
        for task in tasks
    ):
        raise CutoverEvidenceError(
            "task_business_exit_invalid",
            "attempt tasks require explicit or documented terminal business exits",
            details={"identity": "tasks"},
        )
    if kind == "positive":
        eligible = outcome.get("cutover_eligible") is True
        if eligible:
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
    return artifact_map


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
                or sandbox_run_ids
                != {str(provenance.get("sandbox_run_id") or "")}
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
        required_artifact_roles.update({"uniprot_sequences", "uniprot_metadata"})
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
            expected_contract_id=(
                aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
            ),
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
            and scoring_input_bytes
            == scoring_input_result.to_fasta().encode("utf-8")
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
                "selected_accessions": list(
                    aox_reference.HMM_REFERENCE_ACCESSIONS
                ),
            }
            and dict(scoring_reference_selection.get("parameters") or {})
            == {
                "identity_replacement": False,
                "reference_accession": (
                    aox_reference.SCORING_REFERENCE_ACCESSION
                ),
            }
            and dict(scoring_input_assembly.get("parameters") or {})
            == {
                "reference_accession": (
                    aox_reference.SCORING_REFERENCE_ACCESSION
                ),
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
            parsed_artifact_id = str(
                dependency.get("parsed_hit_artifact_id") or ""
            )
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
                    raise ValueError("parsed HMMER row is not bound to a raw response page")
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
                and derivation_identity.get("calculation_id")
                == aox_hmmer.CONTRACT_ID
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
                == str(
                    artifact_roles.get("hmmer_score_filtered_accessions") or ""
                )
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
        join_counts = dict(dict(sequence_join.get("metadata") or {}).get("counts") or {})
        try:
            from openzyme_pipeline import aox_similarity

            target_bytes = _resolve_artifact_path(
                artifact_root,
                str(target_artifact.get("relative_path") or ""),
            ).read_bytes()
            target_count = len(aox_similarity.parse_candidate_fasta(target_bytes).records)
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
                reference_only_valid = _resolve_artifact_path(
                    artifact_root,
                    str(reference_artifact.get("relative_path") or ""),
                ).read_bytes() == _resolve_artifact_path(
                    artifact_root,
                    str(scoring_artifact.get("relative_path") or ""),
                ).read_bytes()
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
            and empty_branch.get("omitted_controlled_roles")
            == expected_omitted_roles
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
            == "canonical_empty_cluster_membership@1"
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
    }
    if (
        workspace != expected_workspace
        or events != expected_events
        or workspace_bytes != canonical_json_bytes(expected_workspace) + b"\n"
        or event_bytes != canonical_json_bytes(expected_events) + b"\n"
        or product_path.get("workspace_projection_digest") != _sha256(workspace_bytes)
        or product_path.get("event_log_digest") != _sha256(event_bytes)
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


def _verify_similarity(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
) -> None:
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
    artifact_fields = {
        "candidate_fasta_artifact_id": "candidate_fasta",
        "membership_artifact_id": "membership_csv",
        "nodes_artifact_id": "nodes_csv",
        "edges_artifact_id": "edges_csv",
        "manifest_artifact_id": "manifest_json",
    }
    resolved: dict[str, bytes] = {}
    for field, label in artifact_fields.items():
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
    if len(resolved) != len(artifact_fields):
        return
    try:
        from openzyme_pipeline import aox_similarity

        aox_similarity.validate_graph_artifacts(
            resolved["candidate_fasta"],
            resolved["membership_csv"],
            resolved["nodes_csv"],
            resolved["edges_csv"],
            resolved["manifest_json"],
            threshold_ppm=int(similarity.get("threshold_ppm")),
            empty_result_reason=(
                None
                if similarity.get("empty_result_reason") is None
                else str(similarity.get("empty_result_reason"))
            ),
            expected_calculation_id=str(similarity.get("calculation_id") or ""),
            expected_calculation_digest=str(similarity.get("calculation_digest") or ""),
            expected_implementation_digest=str(
                similarity.get("implementation_digest") or ""
            ),
            expected_candidate_fasta_digest=str(
                similarity.get("candidate_fasta_digest") or ""
            ),
            expected_membership_digest=str(similarity.get("membership_digest") or ""),
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


def _verify_scientific_outcome(
    payload: Mapping[str, Any],
    *,
    artifact_root: Path,
    artifact_map: Mapping[str, Mapping[str, Any]],
    issues: list[VerificationIssue],
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
        from openzyme_pipeline import aox_motif, aox_similarity

        scoring_result = aox_motif.score_aligned_fasta(
            resolved["alignment"],
            expected_contract_id=str(scoring.get("scoring_contract_id") or ""),
            expected_contract_digest=str(scoring.get("scoring_contract_digest") or ""),
            expected_implementation_digest=str(
                scoring.get("scoring_implementation_digest") or ""
            ),
            expected_input_digest=str(scoring.get("input_digest") or ""),
        )
        graph_result = aox_similarity.validate_graph_artifacts(
            resolved["candidates"],
            resolved["membership"],
            resolved["nodes"],
            resolved["edges"],
            resolved["manifest"],
            threshold_ppm=int(similarity.get("threshold_ppm")),
            empty_result_reason=(
                None
                if similarity.get("empty_result_reason") is None
                else str(similarity.get("empty_result_reason"))
            ),
            expected_calculation_id=str(similarity.get("calculation_id") or ""),
            expected_calculation_digest=str(similarity.get("calculation_digest") or ""),
            expected_implementation_digest=str(
                similarity.get("implementation_digest") or ""
            ),
            expected_candidate_fasta_digest=str(
                similarity.get("candidate_fasta_digest") or ""
            ),
            expected_membership_digest=str(similarity.get("membership_digest") or ""),
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
        or fault.get("failure_code") != "artifact_content_digest_mismatch"
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
    failure_operation_id = str(fault.get("terminal_failure_operation_id") or "")
    source_operation = operations.get(source_operation_id)
    failure_operation = operations.get(failure_operation_id)
    provider_records = [
        dict(item)
        for item in payload.get("provider_identities") or []
        if isinstance(item, dict)
    ]
    provider_proved = any(
        record.get("status") == "completed"
        and record.get("operation_id") == source_operation_id
        and _provider_response_bytes_contain_digest(
            bytes(restored),
            record.get("response_digest"),
        )
        and target_artifact_id in set(record.get("artifact_ids") or [])
        for record in provider_records
    )
    source_refs = (
        [] if source_operation is None else source_operation.get("outputs") or []
    )
    failure_refs = (
        [] if failure_operation is None else failure_operation.get("inputs") or []
    )
    source_proved = any(
        isinstance(ref, dict)
        and ref.get("artifact_id") == target_artifact_id
        and ref.get("content_digest") == actual_before
        for ref in source_refs
    ) and (
        source_operation is not None
        and source_operation.get("status") == "completed"
        and source_operation.get("terminal") is True
    )
    failure_proved = (
        failure_operation is not None
        and failure_operation.get("status") in {"failed", "recovery_failed"}
        and failure_operation.get("terminal") is True
        and failure_operation.get("failure_code") == "artifact_content_digest_mismatch"
        and any(
            isinstance(ref, dict)
            and ref.get("artifact_id") == target_artifact_id
            and ref.get("content_digest") == actual_before
            for ref in failure_refs
        )
    )
    if (
        not provider_proved
        or not source_proved
        or not failure_proved
        or not source_operation_id
        or not failure_operation_id
        or source_operation_id == failure_operation_id
    ):
        issues.append(
            VerificationIssue(
                code="fault_operation_attestation_invalid",
                identity="fault_injection",
                message="controlled provider fault is not bound to distinct source and exact terminal failure operations",
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
            "positive_micu_attribution_invalid",
            "eligible positive attempt requires explicit AOX scenario, model, and invocation receipts",
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
            "positive_micu_usage_unattributed",
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
            "MICU ledger hard limit must remain exactly 100M",
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


def _assert_public_safe(payload: object, *, identity: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            child_identity = f"{identity}.{key_text}"
            if _SENSITIVE_KEY_PATTERN.fullmatch(key_text):
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
    if _PRIVATE_URL_PATTERN.search(payload):
        raise CutoverEvidenceError(
            "public_projection_private_url",
            "attempt evidence contains a private provider URL",
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


def _list_of_dicts(mapping: Mapping[str, object], key: str) -> list[dict[str, Any]]:
    values = mapping.get(key) or []
    if not isinstance(values, list) or not all(
        isinstance(value, dict) for value in values
    ):
        raise CutoverEvidenceError(
            "bundle_collection_invalid",
            f"{key} must be an array of objects",
            details={"identity": key},
        )
    return [dict(value) for value in values]


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
    "AoxCutoverCampaign",
    "ATTEMPT_BUNDLE_SCHEMA_ID",
    "AttemptRunContext",
    "AttemptRunRecord",
    "BlankWorldRoots",
    "CAMPAIGN_DECISION_SCHEMA_ID",
    "canonical_digest",
    "canonical_json_bytes",
    "build_attempt_bundle",
    "create_blank_world_roots",
    "CutoverEvidenceError",
    "evaluate_campaign",
    "FAULT_ARTIFACT_BYTE_FLIP_ID",
    "inject_artifact_byte_flip",
    "KNOWN_POSITIVE_PROBE_SCHEMA_ID",
    "safe_micu_ledger_snapshot",
    "seal_campaign_decision",
    "seal_attempt_bundle",
    "VerificationIssue",
    "VerificationResult",
    "verify_attempt_bundle",
]
