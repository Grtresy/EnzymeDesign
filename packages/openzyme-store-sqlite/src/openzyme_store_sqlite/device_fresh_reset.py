"""Offline, exact-path device reset operator owned by the SQLite Adapter.

This module is deployment tooling.  It is deliberately outside Kernel and
never participates in normal startup or Agent-visible tool registration.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable, Mapping, Sequence

from openzyme_contracts import require_digest, require_identifier


INVENTORY_SCHEMA = "device_fresh_install_reset_inventory@2"
OCCURRENCE_SCHEMA = "device_fresh_install_deletion_occurrence@2"
PERMISSION_ADJUSTMENT_SCHEMA = "device_fresh_install_permission_adjustment@2"
RECEIPT_SCHEMA = "device_fresh_install_reset_receipt@2"
REQUIRED_EXCLUSION_KINDS = frozenset(
    {
        "source_tree",
        "git_history",
        "openspec_history",
        "current_repository_git_lfs_truth",
    }
)
COMPONENT_KINDS = frozenset(
    {"control_store", "repository_service", "runtime_state", "plugin_state"}
)


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class DeviceFreshResetError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        phase: str,
        identity: str | None,
        expected: object,
        observed: object,
        operator_action: str,
        mutation_applied: bool,
    ) -> None:
        self.error_code = error_code
        self.phase = phase
        self.identity = identity
        self.expected = expected
        self.observed = observed
        self.operator_action = operator_action
        self.mutation_applied = mutation_applied
        self.fallback_performed = False
        diagnostic_payload = {
            "error_code": error_code,
            "phase": phase,
            "identity": identity,
            "expected": expected,
            "observed": observed,
            "operator_action": operator_action,
            "mutation_applied": mutation_applied,
            "fallback_performed": False,
        }
        self.diagnostic_id = canonical_digest(diagnostic_payload)
        super().__init__(
            f"{error_code}: {message}; phase={phase}; identity={identity!r}; "
            f"expected={expected!r}; observed={observed!r}; "
            f"operator_action={operator_action}; "
            f"mutation_applied={str(mutation_applied).lower()}; "
            "fallback_performed=false; "
            f"diagnostic_id={self.diagnostic_id}"
        )


@dataclass(frozen=True, slots=True)
class TargetRoot:
    path: Path
    target_kind: str
    owner_evidence: str
    preserve_root: bool
    recoverable: bool
    component_kind: str
    component_owner: str
    distribution_id: str
    distribution_manifest_digest: str
    ownership_scope: str


@dataclass(frozen=True, slots=True)
class Exclusion:
    path: Path
    exclusion_kind: str
    reason: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_absolute(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise DeviceFreshResetError(
            "reset_path_invalid",
            "reset plan path must be a non-empty string",
            phase="plan_validation",
            identity=None,
            expected=f"absolute {field}",
            observed=value,
            operator_action="correct_the_explicit_reset_plan",
            mutation_applied=False,
        )
    path = Path(value)
    if not path.is_absolute() or path in {Path("/"), Path("/tmp")}:
        raise DeviceFreshResetError(
            "reset_path_scope_invalid",
            "reset plan path is relative or dangerously broad",
            phase="plan_validation",
            identity=value,
            expected="an explicit absolute leaf or owned deployment root",
            observed=value,
            operator_action="replace_the_path_with_an_exact_owned_target",
            mutation_applied=False,
        )
    return path


def _parse_plan(
    plan: Mapping[str, object],
) -> tuple[tuple[TargetRoot, ...], tuple[Exclusion, ...]]:
    raw_targets = plan.get("targets")
    raw_exclusions = plan.get("exclusions")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise DeviceFreshResetError(
            "reset_targets_missing",
            "reset plan must contain at least one explicit target",
            phase="plan_validation",
            identity=None,
            expected="non-empty targets array",
            observed=raw_targets,
            operator_action="enumerate_exact_openzyme_targets",
            mutation_applied=False,
        )
    if not isinstance(raw_exclusions, list) or not raw_exclusions:
        raise DeviceFreshResetError(
            "reset_exclusions_missing",
            "reset plan must contain explicit protected paths",
            phase="plan_validation",
            identity=None,
            expected="non-empty exclusions array",
            observed=raw_exclusions,
            operator_action="enumerate_git_openspec_source_and_repository_exclusions",
            mutation_applied=False,
        )
    targets: list[TargetRoot] = []
    for raw in raw_targets:
        if not isinstance(raw, dict):
            raise DeviceFreshResetError(
                "reset_target_invalid",
                "target entry must be an object",
                phase="plan_validation",
                identity=None,
                expected="target object",
                observed=raw,
                operator_action="correct_the_explicit_reset_plan",
                mutation_applied=False,
            )
        targets.append(
            TargetRoot(
                path=_require_absolute(raw.get("path"), field="target path"),
                target_kind=str(raw.get("target_kind", "")),
                owner_evidence=str(raw.get("owner_evidence", "")),
                preserve_root=raw.get("preserve_root") is True,
                recoverable=raw.get("recoverable") is True,
                component_kind=str(raw.get("component_kind", "")),
                component_owner=str(raw.get("component_owner", "")),
                distribution_id=str(raw.get("distribution_id", "")),
                distribution_manifest_digest=str(
                    raw.get("distribution_manifest_digest", "")
                ),
                ownership_scope=str(raw.get("ownership_scope", "")),
            )
        )
    exclusions: list[Exclusion] = []
    for raw in raw_exclusions:
        if not isinstance(raw, dict):
            raise DeviceFreshResetError(
                "reset_exclusion_invalid",
                "exclusion entry must be an object",
                phase="plan_validation",
                identity=None,
                expected="exclusion object",
                observed=raw,
                operator_action="correct_the_explicit_reset_plan",
                mutation_applied=False,
            )
        exclusions.append(
            Exclusion(
                path=_require_absolute(raw.get("path"), field="exclusion path"),
                exclusion_kind=str(raw.get("exclusion_kind", "")),
                reason=str(raw.get("reason", "")),
            )
        )
    for target in targets:
        if (
            not target.target_kind
            or not target.owner_evidence
            or target.component_kind not in COMPONENT_KINDS
            or not target.component_owner
            or not target.distribution_id
            or target.ownership_scope != "exact_tree"
            or not target.distribution_manifest_digest.startswith("sha256:")
        ):
            raise DeviceFreshResetError(
                "reset_target_owner_missing",
                "target lacks kind or OpenZyme owner evidence",
                phase="plan_validation",
                identity=str(target.path),
                expected=(
                    "target kind/owner evidence, closed component kind, owner, "
                    "Distribution identity/digest and exact_tree ownership"
                ),
                observed={
                    "target_kind": target.target_kind,
                    "owner_evidence": target.owner_evidence,
                    "component_kind": target.component_kind,
                    "component_owner": target.component_owner,
                    "distribution_id": target.distribution_id,
                    "distribution_manifest_digest": (
                        target.distribution_manifest_digest
                    ),
                    "ownership_scope": target.ownership_scope,
                },
                operator_action="record_the_current_configuration_or_runtime_owner",
                mutation_applied=False,
            )
    for exclusion in exclusions:
        if not exclusion.exclusion_kind or not exclusion.reason:
            raise DeviceFreshResetError(
                "reset_exclusion_reason_missing",
                "exclusion lacks kind or reason",
                phase="plan_validation",
                identity=str(exclusion.path),
                expected="non-empty exclusion_kind and reason",
                observed={
                    "exclusion_kind": exclusion.exclusion_kind,
                    "reason": exclusion.reason,
                },
                operator_action="record_why_the_path_must_be_preserved",
                mutation_applied=False,
            )
    observed_exclusion_kinds = {item.exclusion_kind for item in exclusions}
    missing_exclusions = sorted(REQUIRED_EXCLUSION_KINDS - observed_exclusion_kinds)
    if missing_exclusions:
        raise DeviceFreshResetError(
            "reset_required_exclusion_missing",
            "reset plan omits a required protected authority root",
            phase="exclusion_validation",
            identity=None,
            expected=sorted(REQUIRED_EXCLUSION_KINDS),
            observed=sorted(observed_exclusion_kinds),
            operator_action="enumerate_every_required_protected_root",
            mutation_applied=False,
        )
    target_paths = tuple(target.path for target in targets)
    if len(set(target_paths)) != len(target_paths):
        raise DeviceFreshResetError(
            "reset_target_duplicate",
            "reset plan contains duplicate targets",
            phase="plan_validation",
            identity=None,
            expected="unique targets",
            observed=[str(path) for path in target_paths],
            operator_action="deduplicate_the_explicit_reset_plan",
            mutation_applied=False,
        )
    for index, left in enumerate(target_paths):
        for right in target_paths[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise DeviceFreshResetError(
                    "reset_target_overlap",
                    "reset targets overlap and would create ambiguous occurrences",
                    phase="plan_validation",
                    identity=str(left),
                    expected="non-overlapping exact targets",
                    observed=str(right),
                    operator_action="keep_only_the_owned_parent_or_exact_leaf_targets",
                    mutation_applied=False,
                )
    for target in targets:
        for exclusion in exclusions:
            if (
                target.path == exclusion.path
                or target.path in exclusion.path.parents
                or exclusion.path in target.path.parents
            ):
                raise DeviceFreshResetError(
                    "reset_exclusion_overlap",
                    "target crosses an explicit protected path",
                    phase="exclusion_validation",
                    identity=str(target.path),
                    expected="no target/exclusion ancestry overlap",
                    observed=str(exclusion.path),
                    operator_action="remove_the_target_or_narrow_it_to_a_non_protected_leaf",
                    mutation_applied=False,
                )
    return tuple(targets), tuple(exclusions)


def _path_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "unsupported"


def _file_digest(path: Path, *, kind: str) -> str | None:
    if kind == "file":
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    if kind == "symlink":
        return canonical_digest(os.readlink(path))
    return None


def _item(path: Path, *, root: TargetRoot) -> dict[str, object]:
    observed = path.lstat()
    kind = _path_kind(observed.st_mode)
    if kind == "unsupported":
        raise DeviceFreshResetError(
            "reset_target_type_unsupported",
            "reset refuses device, socket, fifo, or other special entries",
            phase="inventory_collection",
            identity=str(path),
            expected="file, directory, or symlink",
            observed=stat.filemode(observed.st_mode),
            operator_action="settle_the_owner_and_classify_the_special_entry",
            mutation_applied=False,
        )
    payload: dict[str, object] = {
        "path": str(path),
        "root_path": str(root.path),
        "target_kind": root.target_kind,
        "owner_evidence": root.owner_evidence,
        "component_kind": root.component_kind,
        "component_owner": root.component_owner,
        "distribution_id": root.distribution_id,
        "distribution_manifest_digest": root.distribution_manifest_digest,
        "ownership_scope": root.ownership_scope,
        "kind": kind,
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "mode": stat.S_IMODE(observed.st_mode),
        "uid": observed.st_uid,
        "gid": observed.st_gid,
        "size_bytes": observed.st_size,
        "link_count": observed.st_nlink,
        "content_digest": _file_digest(path, kind=kind),
        "recoverable": root.recoverable,
        "delete_occurrence": path != root.path or not root.preserve_root,
    }
    payload["item_digest"] = canonical_digest(payload)
    return payload


def _walk(root: TargetRoot) -> tuple[dict[str, object], ...]:
    if not root.path.exists() and not root.path.is_symlink():
        raise DeviceFreshResetError(
            "reset_target_absent",
            "planned target was absent during inventory freeze",
            phase="inventory_collection",
            identity=str(root.path),
            expected="existing exact target",
            observed="absent",
            operator_action="refresh_the_read_only_plan_without_claiming_deletion",
            mutation_applied=False,
        )
    root_item = _item(root.path, root=root)
    items = [root_item]
    if root_item["kind"] != "directory":
        return tuple(items)
    root_device = int(root_item["device"])
    pending = [root.path]
    while pending:
        directory = pending.pop()
        for entry in sorted(os.scandir(directory), key=lambda value: value.name):
            path = Path(entry.path)
            item = _item(path, root=root)
            if int(item["device"]) != root_device:
                raise DeviceFreshResetError(
                    "reset_mount_boundary_crossed",
                    "target traversal crossed a filesystem device boundary",
                    phase="inventory_collection",
                    identity=str(path),
                    expected=root_device,
                    observed=item["device"],
                    operator_action="split_or_exclude_the_mounted_storage_explicitly",
                    mutation_applied=False,
                )
            items.append(item)
            if item["kind"] == "directory":
                pending.append(path)
    return tuple(items)


def freeze_inventory(
    plan: Mapping[str, object],
    *,
    source_identity: str,
    quiescence_digest: str,
) -> dict[str, object]:
    targets, exclusions = _parse_plan(plan)
    items = tuple(item for target in targets for item in _walk(target))
    paths = [str(item["path"]) for item in items]
    if len(paths) != len(set(paths)):
        raise DeviceFreshResetError(
            "reset_occurrence_duplicate",
            "inventory traversal produced duplicate path occurrences",
            phase="inventory_collection",
            identity=None,
            expected="unique occurrence paths",
            observed=paths,
            operator_action="correct_overlapping_or_hardlinked_plan_roots",
            mutation_applied=False,
        )
    payload: dict[str, object] = {
        "schema_version": INVENTORY_SCHEMA,
        "source_identity": source_identity,
        "quiescence_digest": quiescence_digest,
        "recoverable": all(bool(item["recoverable"]) for item in items),
        "unresolved_targets": [],
        "targets": [
            {
                "path": str(target.path),
                "target_kind": target.target_kind,
                "owner_evidence": target.owner_evidence,
                "preserve_root": target.preserve_root,
                "recoverable": target.recoverable,
                "component_kind": target.component_kind,
                "component_owner": target.component_owner,
                "distribution_id": target.distribution_id,
                "distribution_manifest_digest": (
                    target.distribution_manifest_digest
                ),
                "ownership_scope": target.ownership_scope,
            }
            for target in targets
        ],
        "exclusions": [
            {
                "path": str(exclusion.path),
                "exclusion_kind": exclusion.exclusion_kind,
                "reason": exclusion.reason,
            }
            for exclusion in exclusions
        ],
        "items": list(items),
        "item_count": len(items),
        "deletion_occurrence_count": sum(
            1 for item in items if item["delete_occurrence"] is True
        ),
        "byte_total": sum(int(item["size_bytes"]) for item in items),
    }
    payload["inventory_digest"] = canonical_digest(payload)
    return payload


def _verify_inventory_digest(inventory: Mapping[str, object]) -> None:
    stored = inventory.get("inventory_digest")
    payload = {key: value for key, value in inventory.items() if key != "inventory_digest"}
    observed = canonical_digest(payload)
    if inventory.get("schema_version") != INVENTORY_SCHEMA or stored != observed:
        raise DeviceFreshResetError(
            "reset_inventory_digest_mismatch",
            "frozen inventory is malformed or has been modified",
            phase="inventory_verification",
            identity=None,
            expected={"schema_version": INVENTORY_SCHEMA, "digest": stored},
            observed={
                "schema_version": inventory.get("schema_version"),
                "digest": observed,
            },
            operator_action="freeze_a_new_read_only_inventory",
            mutation_applied=False,
        )


def _observed_item(path: Path, expected: Mapping[str, object]) -> dict[str, object]:
    root = TargetRoot(
        path=Path(str(expected["root_path"])),
        target_kind=str(expected["target_kind"]),
        owner_evidence=str(expected["owner_evidence"]),
        preserve_root=False,
        recoverable=bool(expected["recoverable"]),
        component_kind=str(expected["component_kind"]),
        component_owner=str(expected["component_owner"]),
        distribution_id=str(expected["distribution_id"]),
        distribution_manifest_digest=str(
            expected["distribution_manifest_digest"]
        ),
        ownership_scope=str(expected["ownership_scope"]),
    )
    return _item(path, root=root)


def _matching_item(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
    *,
    adjusted_mode: int | None = None,
) -> bool:
    ignored = {"delete_occurrence", "item_digest", "link_count"}
    if expected.get("kind") == "directory":
        # Removing an enumerated child legitimately changes the parent's directory
        # entry size and link count.  Device/inode/type/mode/owner remain stable,
        # while every child is independently identity-bound and occurrence-logged.
        ignored.add("size_bytes")
    expected_values = {
        key: value for key, value in expected.items() if key not in ignored
    }
    if adjusted_mode is not None:
        expected_values["mode"] = adjusted_mode
    return expected_values == {
        key: value for key, value in observed.items() if key not in ignored
    }


def load_occurrences(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    occurrences: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            stored_digest = value.get("occurrence_digest") if isinstance(value, dict) else None
            payload = (
                {key: item for key, item in value.items() if key != "occurrence_digest"}
                if isinstance(value, dict)
                else {}
            )
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != OCCURRENCE_SCHEMA
                or stored_digest != canonical_digest(payload)
            ):
                raise DeviceFreshResetError(
                    "reset_occurrence_log_invalid",
                    "deletion occurrence log contains an invalid row",
                    phase="occurrence_log_verification",
                    identity=str(path),
                    expected=OCCURRENCE_SCHEMA,
                    observed={"line": line_number, "value": value},
                    operator_action="inspect_the_private_occurrence_log",
                    mutation_applied=False,
                )
            occurrence_path = str(value.get("path", ""))
            if not occurrence_path or occurrence_path in occurrences:
                raise DeviceFreshResetError(
                    "reset_occurrence_log_duplicate",
                    "deletion occurrence log has an empty or duplicate identity",
                    phase="occurrence_log_verification",
                    identity=occurrence_path or str(path),
                    expected="one row per deleted path",
                    observed={"line": line_number},
                    operator_action="inspect_the_private_occurrence_log",
                    mutation_applied=False,
                )
            occurrences[occurrence_path] = value
    return occurrences


def load_permission_adjustments(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    adjustments: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            stored_digest = value.get("adjustment_digest") if isinstance(value, dict) else None
            payload = (
                {key: item for key, item in value.items() if key != "adjustment_digest"}
                if isinstance(value, dict)
                else {}
            )
            observed_digest = canonical_digest(payload)
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != PERMISSION_ADJUSTMENT_SCHEMA
                or stored_digest != observed_digest
            ):
                raise DeviceFreshResetError(
                    "reset_permission_log_invalid",
                    "permission adjustment log contains an invalid row",
                    phase="permission_log_verification",
                    identity=str(path),
                    expected=PERMISSION_ADJUSTMENT_SCHEMA,
                    observed={"line": line_number, "value": value},
                    operator_action="inspect_the_private_permission_log",
                    mutation_applied=True,
                )
            adjustment_path = str(value.get("path", ""))
            if not adjustment_path or adjustment_path in adjustments:
                raise DeviceFreshResetError(
                    "reset_permission_log_duplicate",
                    "permission log has an empty or duplicate identity",
                    phase="permission_log_verification",
                    identity=adjustment_path or str(path),
                    expected="one adjustment per exact directory",
                    observed={"line": line_number},
                    operator_action="inspect_the_private_permission_log",
                    mutation_applied=True,
                )
            adjustments[adjustment_path] = value
    return adjustments


def verify_inventory(
    inventory: Mapping[str, object],
    *,
    occurrences: Mapping[str, Mapping[str, object]] | None = None,
    permission_adjustments: Mapping[str, Mapping[str, object]] | None = None,
    allowed_replacements: Mapping[str, Mapping[str, object]] | None = None,
) -> None:
    _verify_inventory_digest(inventory)
    recorded = occurrences or {}
    adjusted = permission_adjustments or {}
    replacements = allowed_replacements or {}
    items = inventory.get("items")
    if not isinstance(items, list):
        raise DeviceFreshResetError(
            "reset_inventory_items_invalid",
            "inventory items are not an array",
            phase="inventory_verification",
            identity=None,
            expected="items array",
            observed=items,
            operator_action="freeze_a_new_read_only_inventory",
            mutation_applied=False,
        )
    expected_paths = {str(item["path"]) for item in items if isinstance(item, dict)}
    extra_recorded = sorted(set(recorded) - expected_paths)
    if extra_recorded:
        raise DeviceFreshResetError(
            "reset_occurrence_outside_inventory",
            "occurrence log names paths outside the frozen inventory",
            phase="occurrence_log_verification",
            identity=None,
            expected="only frozen paths",
            observed=extra_recorded,
            operator_action="stop_and_inspect_the_private_occurrence_log",
            mutation_applied=bool(recorded),
        )
    extra_adjusted = sorted(set(adjusted) - expected_paths)
    if extra_adjusted:
        raise DeviceFreshResetError(
            "reset_permission_outside_inventory",
            "permission log names paths outside the frozen inventory",
            phase="permission_log_verification",
            identity=None,
            expected="only frozen directories",
            observed=extra_adjusted,
            operator_action="stop_and_inspect_the_private_permission_log",
            mutation_applied=True,
        )
    extra_replacements = sorted(set(replacements) - expected_paths)
    if extra_replacements:
        raise DeviceFreshResetError(
            "reset_replacement_outside_inventory",
            "replacement proof names a path outside the frozen inventory",
            phase="replacement_verification",
            identity=None,
            expected="only a frozen deployment locator",
            observed=extra_replacements,
            operator_action="stop_and_inspect_the_fresh_database_identity",
            mutation_applied=True,
        )
    for expected in items:
        if not isinstance(expected, dict):
            raise DeviceFreshResetError(
                "reset_inventory_item_invalid",
                "inventory contains a non-object item",
                phase="inventory_verification",
                identity=None,
                expected="item object",
                observed=expected,
                operator_action="freeze_a_new_read_only_inventory",
                mutation_applied=bool(recorded),
            )
        path = Path(str(expected["path"]))
        occurrence = recorded.get(str(path))
        adjustment = adjusted.get(str(path))
        if adjustment is not None and (
            expected.get("kind") != "directory"
            or adjustment.get("item_digest") != expected.get("item_digest")
            or adjustment.get("original_mode") != expected.get("mode")
            or not isinstance(adjustment.get("adjusted_mode"), int)
        ):
            raise DeviceFreshResetError(
                "reset_permission_identity_mismatch",
                "permission adjustment is not bound to the frozen directory",
                phase="permission_log_verification",
                identity=str(path),
                expected={
                    "kind": "directory",
                    "item_digest": expected.get("item_digest"),
                    "original_mode": expected.get("mode"),
                },
                observed=adjustment,
                operator_action="stop_and_inspect_the_private_permission_log",
                mutation_applied=True,
            )
        exists = path.exists() or path.is_symlink()
        if occurrence is not None:
            if occurrence.get("item_digest") != expected.get("item_digest"):
                raise DeviceFreshResetError(
                    "reset_occurrence_identity_mismatch",
                    "occurrence does not bind the frozen item",
                    phase="occurrence_log_verification",
                    identity=str(path),
                    expected=expected.get("item_digest"),
                    observed=occurrence.get("item_digest"),
                    operator_action="stop_and_inspect_the_private_occurrence_log",
                    mutation_applied=True,
                )
            if exists:
                replacement = replacements.get(str(path))
                current = _observed_item(path, expected)
                replacement_matches = (
                    replacement is not None
                    and current["kind"] == "file"
                    and current["device"] == replacement.get("device")
                    and current["inode"] == replacement.get("inode")
                    and current["content_digest"]
                    == replacement.get("content_digest")
                    and current["content_digest"] != expected.get("content_digest")
                    and isinstance(
                        replacement.get("fresh_bootstrap_receipt_digest"), str
                    )
                    and str(
                        replacement.get("fresh_bootstrap_receipt_digest")
                    ).startswith("sha256:")
                )
                if not replacement_matches:
                    raise DeviceFreshResetError(
                        "reset_recorded_path_reappeared",
                        "a recorded deleted path exists without an exact fresh replacement proof",
                        phase="post_delete_verification",
                        identity=str(path),
                        expected={"absent": True, "allowed_replacement": replacement},
                        observed=current,
                        operator_action="stop_the_writer_and_verify_the_fresh_database_identity",
                        mutation_applied=True,
                    )
            continue
        if not exists:
            raise DeviceFreshResetError(
                "reset_unrecorded_path_absent",
                "frozen target disappeared without a durable occurrence",
                phase="pre_delete_verification",
                identity=str(path),
                expected="present or durably recorded removed",
                observed="absent",
                operator_action="stop_and_reconcile_the_external_mutation",
                mutation_applied=bool(recorded),
            )
        observed = _observed_item(path, expected)
        adjusted_mode = (
            int(adjustment["adjusted_mode"]) if adjustment is not None else None
        )
        if not _matching_item(expected, observed, adjusted_mode=adjusted_mode):
            raise DeviceFreshResetError(
                "reset_target_identity_drift",
                "target identity changed after inventory freeze",
                phase="pre_delete_verification",
                identity=str(path),
                expected=expected,
                observed=observed,
                operator_action="freeze_a_new_inventory_after_quiescence",
                mutation_applied=bool(recorded),
            )


def _append_occurrence(
    log_path: Path,
    occurrence: Mapping[str, object],
) -> None:
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(
        occurrence,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(encoded + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _prepare_owned_directory_permissions(
    inventory: Mapping[str, object],
    *,
    occurrences: Mapping[str, Mapping[str, object]],
    permission_log_path: Path,
) -> dict[str, dict[str, object]]:
    adjustments = load_permission_adjustments(permission_log_path)
    items = inventory.get("items")
    assert isinstance(items, list)
    current_uid = os.geteuid()
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("kind") != "directory"
            or item.get("delete_occurrence") is not True
            or str(item["path"]) in occurrences
            or str(item["path"]) in adjustments
        ):
            continue
        original_mode = int(item["mode"])
        required = stat.S_IWUSR | stat.S_IXUSR
        if original_mode & required == required:
            continue
        path = Path(str(item["path"]))
        observed = _observed_item(path, item)
        if not _matching_item(item, observed) or int(item["uid"]) != current_uid:
            raise DeviceFreshResetError(
                "reset_permission_adjustment_unauthorized",
                "read-only directory is not the exact current-user-owned frozen item",
                phase="permission_adjustment",
                identity=str(path),
                expected={"item": item, "effective_uid": current_uid},
                observed=observed,
                operator_action="stop_and_resolve_the_directory_owner",
                mutation_applied=bool(occurrences or adjustments),
            )
        adjusted_mode = original_mode | required
        try:
            path.chmod(adjusted_mode, follow_symlinks=False)
        except OSError as exc:
            raise DeviceFreshResetError(
                "reset_permission_adjustment_failed",
                "exact owned directory could not be made removable",
                phase="permission_adjustment",
                identity=str(path),
                expected={"original_mode": original_mode, "adjusted_mode": adjusted_mode},
                observed={
                    "exception_type": type(exc).__name__,
                    "errno": exc.errno,
                    "message": str(exc),
                },
                operator_action="inspect_the_exact_owned_directory",
                mutation_applied=bool(occurrences or adjustments),
            ) from exc
        adjustment: dict[str, object] = {
            "schema_version": PERMISSION_ADJUSTMENT_SCHEMA,
            "path": str(path),
            "item_digest": item["item_digest"],
            "original_mode": original_mode,
            "adjusted_mode": adjusted_mode,
            "adjusted_at": _utc_now(),
            "reason": "enable_exact_owner_deletion_of_frozen_read_only_storage",
            "recoverable": False,
        }
        adjustment["adjustment_digest"] = canonical_digest(adjustment)
        _append_occurrence(permission_log_path, adjustment)
        adjustments[str(path)] = adjustment
    return adjustments


def execute_inventory(
    inventory: Mapping[str, object],
    *,
    occurrence_log_path: Path,
    permission_log_path: Path,
    authorization_digest: str,
) -> tuple[dict[str, object], ...]:
    expected_authorization = canonical_digest(
        {
            "inventory_digest": inventory.get("inventory_digest"),
            "recoverable": False,
            "authorized_scope": "all_resolved_openzyme_old_records_and_storage",
        }
    )
    if authorization_digest != expected_authorization:
        raise DeviceFreshResetError(
            "reset_authorization_digest_mismatch",
            "destructive execution is not bound to this exact inventory",
            phase="authorization_verification",
            identity=None,
            expected=expected_authorization,
            observed=authorization_digest,
            operator_action="bind_authorization_to_the_frozen_inventory",
            mutation_applied=False,
        )
    occurrences = load_occurrences(occurrence_log_path)
    permission_adjustments = load_permission_adjustments(permission_log_path)
    verify_inventory(
        inventory,
        occurrences=occurrences,
        permission_adjustments=permission_adjustments,
    )
    permission_adjustments = _prepare_owned_directory_permissions(
        inventory,
        occurrences=occurrences,
        permission_log_path=permission_log_path,
    )
    verify_inventory(
        inventory,
        occurrences=occurrences,
        permission_adjustments=permission_adjustments,
    )
    raw_items = inventory["items"]
    assert isinstance(raw_items, list)
    items = [
        item
        for item in raw_items
        if isinstance(item, dict) and item.get("delete_occurrence") is True
    ]
    items.sort(
        key=lambda item: (
            len(Path(str(item["path"])).parts),
            item["kind"] == "directory",
        ),
        reverse=True,
    )
    for item in items:
        path = Path(str(item["path"]))
        if str(path) in occurrences:
            continue
        observed = _observed_item(path, item)
        adjustment = permission_adjustments.get(str(path))
        adjusted_mode = (
            int(adjustment["adjusted_mode"]) if adjustment is not None else None
        )
        if not _matching_item(item, observed, adjusted_mode=adjusted_mode):
            raise DeviceFreshResetError(
                "reset_target_identity_drift",
                "target identity changed immediately before deletion",
                phase="destructive_execution",
                identity=str(path),
                expected=item,
                observed=observed,
                operator_action="stop_and_freeze_a_new_inventory",
                mutation_applied=bool(occurrences),
            )
        try:
            if item["kind"] == "directory":
                path.rmdir()
            else:
                path.unlink()
        except OSError as exc:
            raise DeviceFreshResetError(
                "reset_delete_failed",
                "exact target occurrence could not be deleted",
                phase="destructive_execution",
                identity=str(path),
                expected={"kind": item["kind"], "state": "removed"},
                observed={
                    "exception_type": type(exc).__name__,
                    "errno": exc.errno,
                    "message": str(exc),
                },
                operator_action="inspect_the_exact_path_and_resume_same_inventory",
                mutation_applied=bool(occurrences),
            ) from exc
        occurrence: dict[str, object] = {
            "schema_version": OCCURRENCE_SCHEMA,
            "path": str(path),
            "item_digest": item["item_digest"],
            "state": "removed",
            "removed_at": _utc_now(),
            "recoverable": False,
            "post_delete_absent": not path.exists() and not path.is_symlink(),
        }
        occurrence["occurrence_digest"] = canonical_digest(occurrence)
        _append_occurrence(occurrence_log_path, occurrence)
        occurrences[str(path)] = occurrence
    verify_inventory(
        inventory,
        occurrences=occurrences,
        permission_adjustments=permission_adjustments,
    )
    return tuple(occurrences[path] for path in sorted(occurrences))


def build_reset_receipt(
    *,
    inventory: Mapping[str, object],
    occurrences: Sequence[Mapping[str, object]],
    permission_adjustments: Sequence[Mapping[str, object]],
    source_identity: str,
    quiescence_digest: str,
    zero_scan_digest: str,
    fresh_bootstrap_receipt_digest: str,
    fresh_database_identity_digest: str,
    built_wheel_set_digest: str,
    documentation_set_digest: str,
    target_distribution_id: str,
    target_distribution_version: str,
    target_distribution_manifest_digest: str,
    target_composition_bundle_digest: str,
) -> dict[str, object]:
    _verify_inventory_digest(inventory)
    for field_name, value in (
        ("source_identity", source_identity),
        ("quiescence_digest", quiescence_digest),
        ("zero_scan_digest", zero_scan_digest),
        ("fresh_bootstrap_receipt_digest", fresh_bootstrap_receipt_digest),
        ("fresh_database_identity_digest", fresh_database_identity_digest),
        ("built_wheel_set_digest", built_wheel_set_digest),
        ("documentation_set_digest", documentation_set_digest),
        (
            "target_distribution_manifest_digest",
            target_distribution_manifest_digest,
        ),
        ("target_composition_bundle_digest", target_composition_bundle_digest),
    ):
        require_digest(value, field_name=field_name)
    require_identifier(
        target_distribution_id,
        field_name="target_distribution_id",
    )
    require_identifier(
        target_distribution_version,
        field_name="target_distribution_version",
    )
    expected_count = int(inventory["deletion_occurrence_count"])
    occurrence_digests = sorted(str(row["occurrence_digest"]) for row in occurrences)
    permission_digests = sorted(
        str(row["adjustment_digest"]) for row in permission_adjustments
    )
    if len(occurrence_digests) != expected_count:
        raise DeviceFreshResetError(
            "reset_occurrence_closure_mismatch",
            "receipt requires one durable occurrence per planned deletion",
            phase="receipt_generation",
            identity=None,
            expected=expected_count,
            observed=len(occurrence_digests),
            operator_action="resume_the_same_frozen_inventory",
            mutation_applied=bool(occurrences),
        )
    payload: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA,
        "source_identity": source_identity,
        "inventory_digest": inventory["inventory_digest"],
        "exclusion_set_digest": canonical_digest(inventory["exclusions"]),
        "quiescence_digest": quiescence_digest,
        "deletion_occurrence_set_digest": canonical_digest(occurrence_digests),
        "deletion_occurrence_count": expected_count,
        "permission_adjustment_set_digest": canonical_digest(permission_digests),
        "permission_adjustment_count": len(permission_digests),
        "recoverable": False,
        "zero_scan_digest": zero_scan_digest,
        "fresh_bootstrap_receipt_digest": fresh_bootstrap_receipt_digest,
        "fresh_database_identity_digest": fresh_database_identity_digest,
        "built_wheel_set_digest": built_wheel_set_digest,
        "documentation_set_digest": documentation_set_digest,
        "target_distribution_id": target_distribution_id,
        "target_distribution_version": target_distribution_version,
        "target_distribution_manifest_digest": (
            target_distribution_manifest_digest
        ),
        "target_composition_bundle_digest": target_composition_bundle_digest,
        "authority_scope": "device_maintenance_evidence_only",
        "product_authority": False,
        "scientific_authority": False,
        "runtime_authority": False,
    }
    payload["receipt_digest"] = canonical_digest(payload)
    return payload


def verify_reset_receipt(receipt: Mapping[str, object]) -> None:
    stored = receipt.get("receipt_digest")
    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    observed = canonical_digest(payload)
    if (
        receipt.get("schema_version") != RECEIPT_SCHEMA
        or receipt.get("recoverable") is not False
        or receipt.get("product_authority") is not False
        or receipt.get("scientific_authority") is not False
        or receipt.get("runtime_authority") is not False
        or stored != observed
    ):
        raise DeviceFreshResetError(
            "reset_receipt_invalid",
            "device reset receipt is malformed, authoritative, or digest-drifted",
            phase="receipt_verification",
            identity=None,
            expected={
                "schema_version": RECEIPT_SCHEMA,
                "recoverable": False,
                "authority": False,
                "receipt_digest": stored,
            },
            observed={
                "schema_version": receipt.get("schema_version"),
                "recoverable": receipt.get("recoverable"),
                "product_authority": receipt.get("product_authority"),
                "scientific_authority": receipt.get("scientific_authority"),
                "runtime_authority": receipt.get("runtime_authority"),
                "receipt_digest": observed,
            },
            operator_action="regenerate_from_the_exact_frozen_evidence",
            mutation_applied=True,
        )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze, execute, and verify an exact OpenZyme device fresh reset."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--plan", required=True, type=_absolute_path)
    freeze.add_argument("--output", required=True, type=_absolute_path)
    freeze.add_argument("--source-identity", required=True)
    freeze.add_argument("--quiescence-digest", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--inventory", required=True, type=_absolute_path)
    verify.add_argument("--occurrence-log", type=_absolute_path)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--inventory", required=True, type=_absolute_path)
    execute.add_argument("--occurrence-log", required=True, type=_absolute_path)
    execute.add_argument("--permission-log", required=True, type=_absolute_path)
    execute.add_argument("--authorization-digest", required=True)
    receipt = subparsers.add_parser("verify-receipt")
    receipt.add_argument("--receipt", required=True, type=_absolute_path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "freeze":
        inventory = freeze_inventory(
            _load_json(args.plan),
            source_identity=args.source_identity,
            quiescence_digest=args.quiescence_digest,
        )
        _write_json(args.output, inventory)
        print(json.dumps({
            "inventory_digest": inventory["inventory_digest"],
            "item_count": inventory["item_count"],
            "deletion_occurrence_count": inventory["deletion_occurrence_count"],
        }, sort_keys=True))
        return 0
    if args.command == "verify":
        occurrences = (
            load_occurrences(args.occurrence_log)
            if args.occurrence_log is not None
            else {}
        )
        verify_inventory(_load_json(args.inventory), occurrences=occurrences)
        print(json.dumps({"valid": True, "occurrence_count": len(occurrences)}))
        return 0
    if args.command == "execute":
        occurrences = execute_inventory(
            _load_json(args.inventory),
            occurrence_log_path=args.occurrence_log,
            permission_log_path=args.permission_log,
            authorization_digest=args.authorization_digest,
        )
        print(json.dumps({"complete": True, "occurrence_count": len(occurrences)}))
        return 0
    if args.command == "verify-receipt":
        verify_reset_receipt(_load_json(args.receipt))
        print(json.dumps({"valid": True}))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DeviceFreshResetError",
    "INVENTORY_SCHEMA",
    "OCCURRENCE_SCHEMA",
    "PERMISSION_ADJUSTMENT_SCHEMA",
    "RECEIPT_SCHEMA",
    "build_reset_receipt",
    "canonical_digest",
    "execute_inventory",
    "freeze_inventory",
    "load_occurrences",
    "load_permission_adjustments",
    "verify_inventory",
    "verify_reset_receipt",
]
