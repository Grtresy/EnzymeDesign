from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime
import re
from pathlib import Path, PurePosixPath
from typing import Any

import openzyme_host_api.aox_cutover_evidence as cutover
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import VerificationIssue
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import canonical_json_bytes
from openzyme_host_api.aox_selected_chain_evidence import (
    _verify_selected_chain_control,
)


_EMPTY_RESULT_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_DERIVATION_CONTRACT_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*@[1-9][0-9]*$")


def typed_empty_artifact_validation_receipt(
    *,
    kind: str,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    catalog_metadata = dict(metadata)
    raw_validation = catalog_metadata.get("validation")
    validation = dict(raw_validation) if isinstance(raw_validation, dict) else {}
    format_value = str(catalog_metadata.get("format") or "").lower()
    profile = catalog_metadata.get("validation_profile")
    reason = catalog_metadata.get("empty_result_reason")
    derivation = catalog_metadata.get("derivation_contract_id")
    expected_validation = {
        "status": "passed",
        "format": format_value,
        "required_columns": [],
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": reason,
        "derivation_contract_id": derivation,
    }
    if (
        kind != "sequence"
        or format_value not in {"fa", "faa", "fasta"}
        or profile != "fasta_zero_records@1"
        or not isinstance(reason, str)
        or _EMPTY_RESULT_REASON_PATTERN.fullmatch(reason) is None
        or not isinstance(derivation, str)
        or _DERIVATION_CONTRACT_PATTERN.fullmatch(derivation) is None
        or validation != expected_validation
    ):
        raise CutoverEvidenceError(
            "typed_empty_artifact_validation_invalid",
            "test fixture zero-record validation is invalid",
        )
    return {
        "schema_id": cutover.TYPED_EMPTY_ARTIFACT_VALIDATION_SCHEMA_ID,
        "kind": kind,
        "format": format_value,
        "validation_profile": profile,
        "empty_result_reason": reason,
        "derivation_contract_id": derivation,
        "catalog_validation_digest": canonical_digest(validation),
    }


def project_formal_delegation_request(
    payload: Mapping[str, object], *, document_id: str
) -> dict[str, object]:
    request = dict(payload)
    string_keys = (
        "task_id", "instructions", "role", "agent_id", "nickname",
        "display_name", "handle",
    )
    expected = {*string_keys, "workflow_refs", "workflow_manifests"}
    if not all((
        set(request) == expected,
        isinstance(document_id, str) and bool(document_id),
        all(isinstance(request.get(key), str) and request[key] for key in string_keys),
        isinstance(request.get("workflow_refs"), list),
        all(isinstance(item, str) and item for item in request.get("workflow_refs") or []),
        isinstance(request.get("workflow_manifests"), list),
        all(isinstance(item, dict) for item in request.get("workflow_manifests") or []),
    )):
        raise CutoverEvidenceError(
            "delegation_request_projection_invalid",
            "test delegation request does not match the closed schema",
        )
    projection = {
        "schema_id": cutover.FORMAL_DELEGATION_REQUEST_SCHEMA_ID,
        "document_id": document_id,
        "document_kind": "delegation_request",
        "task_id": request["task_id"],
        "instructions_digest": canonical_digest(request["instructions"]),
        "role": request["role"], "agent_id": request["agent_id"],
        "nickname": request["nickname"], "display_name": request["display_name"],
        "handle": request["handle"], "workflow_refs": list(request["workflow_refs"]),
        "workflow_manifests": [dict(item) for item in request["workflow_manifests"]],
    }
    cutover._assert_public_safe(projection, identity="formal_delegation_request")
    return projection


def seal_source_tree_envelope(
    source_root: Path,
    *,
    expected_source_tree_digest: str,
) -> bytes:
    if source_root.is_symlink() or not source_root.is_dir():
        raise CutoverEvidenceError(
            "sealed_source_tree_root_invalid",
            "test fixture source root is invalid",
        )
    files: list[dict[str, object]] = []
    for source in sorted(
        source_root.rglob("*"),
        key=lambda item: item.relative_to(source_root).as_posix(),
    ):
        relative_path = cutover._safe_source_tree_relative_path(
            source.relative_to(source_root).as_posix()
        )
        if source.is_symlink() or (not source.is_dir() and not source.is_file()):
            raise CutoverEvidenceError(
                "sealed_source_tree_entry_invalid",
                "test fixture source tree has an unsupported entry",
            )
        if source.is_dir():
            continue
        content = source.read_bytes()
        try:
            source_text = content.decode("utf-8")
        except UnicodeDecodeError:
            source_text = None
        if source_text is not None:
            cutover._assert_public_safe(
                source_text,
                identity=f"sealed_source_tree:{relative_path}",
            )
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": len(content),
                "content_digest": cutover._sha256(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    if not files:
        raise CutoverEvidenceError(
            "sealed_source_tree_empty",
            "test fixture source tree is empty",
        )
    tree_material = [
        {
            "relative_path": str(item["relative_path"]),
            "content_digest": str(item["content_digest"]),
            "size_bytes": int(item["size_bytes"]),
        }
        for item in files
    ]
    actual = cutover._source_tree_digest(tree_material)
    if actual != expected_source_tree_digest:
        raise CutoverEvidenceError(
            "sealed_source_tree_digest_mismatch",
            "test fixture source tree digest does not reproduce",
            details={"expected": expected_source_tree_digest, "actual": actual},
        )
    return canonical_json_bytes(
        {
            "schema_id": cutover.SEALED_SOURCE_TREE_SCHEMA_ID,
            "source_tree_digest": actual,
            "files": files,
        }
    ) + b"\n"


def build_attempt_bundle(
    *,
    attempt_id: str,
    attempt_kind: str,
    identity: Mapping[str, object],
    clean_world: Mapping[str, object],
    ledger_before: Mapping[str, object],
    ledger_after: Mapping[str, object],
    artifact_root: Path,
    evidence_payload: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
    sealed_at: str | None = None,
) -> dict[str, Any]:
    source = evidence if evidence is not None else evidence_payload
    assert source is not None
    payload = evidence_module_payload(
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        identity=identity,
        clean_world=clean_world,
        ledger_before=ledger_before,
        ledger_after=ledger_after,
        artifact_root=artifact_root,
        source=source,
        sealed_at=sealed_at,
    )
    cutover._validate_attempt_semantics(payload, artifact_root=artifact_root)
    cutover._assert_public_safe(payload, identity="attempt_bundle")
    return payload


def evidence_module_payload(
    *,
    attempt_id: str,
    attempt_kind: str,
    identity: Mapping[str, object],
    clean_world: Mapping[str, object],
    ledger_before: Mapping[str, object],
    ledger_after: Mapping[str, object],
    artifact_root: Path,
    source: Mapping[str, object],
    sealed_at: str | None,
) -> dict[str, Any]:
    normalized_identity = cutover._normalize_identity(identity)
    before, after = dict(ledger_before), dict(ledger_after)
    cutover._validate_ledger_transition(before, after)
    list_fields = (
        "provider_identities",
        "engine_invocations",
        "toolchain_identities",
        "approvals",
        "operations",
        "tasks",
        "artifacts",
    )
    payload: dict[str, Any] = {
        "schema_id": cutover.ATTEMPT_BUNDLE_SCHEMA_ID,
        "attempt_id": attempt_id,
        "attempt_kind": attempt_kind,
        "sealed_at": sealed_at or datetime.now(UTC).isoformat(),
        "identity": {
            **normalized_identity,
            "identity_digest": canonical_digest(normalized_identity),
        },
        "clean_world": dict(clean_world),
        "micu_ledger": {"before": before, "after": after},
        **{name: _list_of_dicts(source, name) for name in list_fields},
        "known_positive_probe": dict(source.get("known_positive_probe") or {}),
        "product_path": dict(source.get("product_path") or {}),
        "report": dict(source.get("report") or {}),
        "final_answer": dict(source.get("final_answer") or {}),
        "scientific_checks": dict(source.get("scientific_checks") or {}),
        "warnings": list(source.get("warnings") or []),
        "degradations": list(source.get("degradations") or []),
        "scientific_outcome": dict(source.get("scientific_outcome") or {}),
        "fault_injection": (
            None
            if source.get("fault_injection") is None
            else dict(source.get("fault_injection") or {})
        ),
    }
    _normalize_artifacts(payload, artifact_root=artifact_root)
    _normalize_record_digests(payload)
    return payload


def _list_of_dicts(
    mapping: Mapping[str, object], key: str
) -> list[dict[str, Any]]:
    values = mapping.get(key) or []
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise CutoverEvidenceError(
            "bundle_collection_invalid",
            f"{key} must be an array of objects",
            details={"identity": key},
        )
    return [dict(value) for value in values]


def _normalize_artifacts(payload: dict[str, Any], *, artifact_root: Path) -> None:
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(payload["artifacts"]):
        record = dict(raw)
        artifact_id = str(record.get("artifact_id") or "").strip()
        relative_path = str(record.get("relative_path") or "").strip()
        if not artifact_id or artifact_id in seen:
            raise CutoverEvidenceError(
                "artifact_identity_invalid",
                "artifact ids must be non-empty and unique",
                details={"identity": f"artifacts[{index}]"},
            )
        seen.add(artifact_id)
        path = cutover._resolve_artifact_path(artifact_root, relative_path)
        if not path.is_file() or path.is_symlink():
            raise CutoverEvidenceError(
                "artifact_file_invalid",
                "attempt bundle artifacts must be sealed regular files",
                details={"identity": artifact_id},
            )
        provenance = dict(record.get("provenance") or {})
        record.update(
            artifact_id=artifact_id,
            relative_path=PurePosixPath(relative_path).as_posix(),
            scope=str(record.get("scope") or "formal"),
            origin=str(record.get("origin") or "operation"),
            size_bytes=path.stat().st_size,
            content_digest=cutover._sha256(path.read_bytes()),
            provenance=provenance,
            provenance_digest=canonical_digest(provenance),
        )
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
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in payload[collection]:
            record = dict(raw)
            identity = str(record.get(identity_key) or "").strip()
            if not identity or identity in seen:
                raise CutoverEvidenceError(
                    "record_identity_invalid",
                    f"{collection} records require unique non-empty {identity_key}",
                    details={"identity": collection},
                )
            seen.add(identity)
            record[digest_key] = canonical_digest(
                {key: value for key, value in record.items() if key != digest_key}
            )
            records.append(record)
        payload[collection] = sorted(records, key=lambda item: str(item[identity_key]))
    for name in ("known_positive_probe", "report"):
        record = dict(payload[name])
        if name == "known_positive_probe":
            record.setdefault("schema_id", cutover.KNOWN_POSITIVE_PROBE_SCHEMA_ID)
        record["record_digest"] = canonical_digest(
            {key: value for key, value in record.items() if key != "record_digest"}
        )
        payload[name] = record
    answer = dict(payload["final_answer"])
    answer["content_digest"] = cutover._sha256(
        str(answer.get("content") or "").encode()
    )
    payload["final_answer"] = answer


def inject_artifact_byte_flip(
    artifact_root: Path,
    *,
    relative_path: str,
    byte_offset: int = 0,
) -> dict[str, Any]:
    target = cutover._resolve_artifact_path(artifact_root, relative_path)
    content = target.read_bytes()
    if not content:
        raise CutoverEvidenceError(
            "fault_target_empty",
            "byte-flip test target must be non-empty",
            details={"relative_path": relative_path},
        )
    if byte_offset < 0 or byte_offset >= len(content):
        raise CutoverEvidenceError(
            "fault_offset_invalid",
            "byte-flip test offset is outside the artifact",
            details={"byte_offset": byte_offset, "size_bytes": len(content)},
        )
    mutated = bytearray(content)
    mutated[byte_offset] ^= 1
    target.chmod(0o600)
    target.write_bytes(mutated)
    target.chmod(0o444)
    return {
        "fault_id": cutover.FAULT_ARTIFACT_BYTE_FLIP_ID,
        "relative_path": relative_path,
        "byte_offset": byte_offset,
        "before_digest": cutover._sha256(content),
        "after_digest": cutover._sha256(bytes(mutated)),
        "reached_target_seam": True,
    }


def seal_attempt_bundle(payload: Mapping[str, object], destination: Path) -> str:
    normalized = dict(payload)
    bundle_digest = canonical_digest(normalized)
    cutover._write_append_only_bytes(
        destination,
        canonical_json_bytes(
            {"payload": normalized, "bundle_digest": bundle_digest}
        )
        + b"\n",
        error_code="attempt_bundle_append_only",
        error_message="attempt bundle already exists",
    )
    return bundle_digest


def build_selected_chain_attempt_bundle(
    *,
    attempt_id: str,
    attempt_kind: str,
    identity: Mapping[str, object],
    clean_world: Mapping[str, object],
    ledger_before: Mapping[str, object],
    ledger_after: Mapping[str, object],
    artifact_root: Path,
    evidence: Mapping[str, object],
    scientific_attempt_control: Mapping[str, object],
    sealed_at: str | None = None,
) -> dict[str, Any]:
    payload = evidence_module_payload(
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        identity=identity,
        clean_world=clean_world,
        ledger_before=ledger_before,
        ledger_after=ledger_after,
        artifact_root=artifact_root,
        source=evidence,
        sealed_at=sealed_at,
    )
    cutover._validate_attempt_semantics(
        payload,
        artifact_root=artifact_root,
        current_supervision=True,
    )
    control = dict(scientific_attempt_control)
    issues: list[VerificationIssue] = []
    _verify_selected_chain_control(payload, control=control, issues=issues)
    if issues:
        first = issues[0]
        raise CutoverEvidenceError(
            first.code,
            first.message,
            details={"identity": first.identity},
        )
    selected = {
        **payload,
        "schema_id": cutover.ATTEMPT_BUNDLE_SCHEMA_ID_V3,
        "scientific_attempt_control": control,
    }
    cutover._assert_public_safe(
        selected,
        identity="selected_chain_attempt_bundle",
    )
    return selected


__all__ = [
    "build_attempt_bundle",
    "build_selected_chain_attempt_bundle",
    "seal_attempt_bundle",
    "seal_source_tree_envelope",
    "typed_empty_artifact_validation_receipt",
]
