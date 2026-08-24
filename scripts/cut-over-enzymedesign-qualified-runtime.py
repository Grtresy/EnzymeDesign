#!/usr/bin/env python3
"""Source-bound Batch-1 cutover and first-live workflow for EnzymeDesign.

The command intentionally keeps qualification, cutover and the first live
occurrence as three different persisted identities.  It never loads ambient
credentials and the post-cutover smoke uses the adopted public UniProt route.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Mapping
from typing import Sequence

from enzymedesign_bio_provider_adapters import HttpBioProviderAdapter
from enzymedesign_distribution import CutoverMonitoringSnapshot
from enzymedesign_distribution import CutoverQuiescenceSeal
from enzymedesign_distribution import CutoverRollbackReceipt
from enzymedesign_distribution import CutoverStartupProof
from enzymedesign_distribution import FirstLiveBoundaryReceipt
from enzymedesign_distribution import PostCutoverSmokeAuthority
from enzymedesign_distribution import PostCutoverSmokePlan
from enzymedesign_distribution import PostCutoverSmokeReceipt
from enzymedesign_distribution import ProtectedQualifiedRuntimeState
from enzymedesign_distribution import QualificationSourceCompatibilityProof
from enzymedesign_distribution import QualifiedRuntimeCutoverAuthority
from enzymedesign_distribution import QualifiedRuntimeCutoverError
from enzymedesign_distribution import QualifiedRuntimeCutoverPlan
from enzymedesign_distribution import QualifiedRuntimeCutoverReceipt
from enzymedesign_distribution import activate_enzymedesign_composition
from enzymedesign_distribution import backup_manifest_payload
from enzymedesign_distribution import build_adoption_ledger
from enzymedesign_distribution import load_adoption_ledger
from enzymedesign_distribution import verify_batch_1_adoption_evidence
from openzyme_contracts import canonical_sha256_digest
from test_gate.source import collect_source_identity


REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR_ID = "operator.enzymedesign-owner"
QUALIFICATION_COMMIT = "bb6af997c369dd03d4d637ca27c284d9006447fd"
QUALIFICATION_ROOT = Path(
    "/home/grtresy/.local/state/openzyme/qualification-enzymedesign"
)
PRIVATE_EVIDENCE_ROOT = QUALIFICATION_ROOT / "private-evidence"
PACKET_PATH = (
    PRIVATE_EVIDENCE_ROOT
    / "post-preparation-packet-source-rebound-bb6af99-20260824.json"
)
AUTHORIZATION_PATH = (
    QUALIFICATION_ROOT
    / "qualification-authorization-authorization.qualification.batch-1."
    "sealed-bb6af99-20260824T090540+0800.json"
)
QUALIFICATION_LEDGER_PATH = QUALIFICATION_ROOT / "qualification.sqlite3"
QUALIFICATION_REPORT_PATH = (
    PRIVATE_EVIDENCE_ROOT
    / "qualification-report-authorization.qualification.batch-1."
    "sealed-bb6af99-20260824T090540+0800.json"
)
RECEIPT_SET_PATH = (
    PRIVATE_EVIDENCE_ROOT
    / "qualification-receipt-set-authorization.qualification.batch-1."
    "sealed-bb6af99-20260824T090540+0800.json"
)
COMPOSITION_PATH = (
    REPO_ROOT
    / "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "openzyme-composition.toml"
)

QUALIFIED_OWNER_PATHS = (
    "packages/openzyme-runtime-llm",
    "packages/openzyme-research-tavily",
    "packages/enzymedesign-bio-provider-adapters",
    "packages/openzyme-workspace-git-lfs",
    "packages/openzyme-process-podman",
    "packages/openzyme-hpc-ssh",
    "packages/openzyme-hpc-slurm",
    "packages/enzymedesign-hmmer",
    "packages/enzymedesign-vina",
    "packages/enzymedesign-structure",
    "packages/enzymedesign-docking-preprocess",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "external_qualification.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_admission.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_bridges.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_compute.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_live_bridges.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_live_runtime.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_operator_state.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_planning.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_preparation_runtime.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_private_diagnostics.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_runtime.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_scientific_workloads.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualification_workspace_runtime.py",
)
ALLOWED_CUTOVER_PREFIXES = (
    "docs/",
    "openspec/",
    "packages/enzymedesign-distribution/README.md",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/__init__.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "application_runtime.py",
    "packages/enzymedesign-distribution/src/enzymedesign_distribution/"
    "qualified_runtime_cutover.py",
    "packages/enzymedesign-distribution/tests/test_qualified_runtime_cutover.py",
    "scripts/cut-over-enzymedesign-qualified-runtime.py",
)
WRITERS = (
    "agent-runtime.enzymedesign",
    "git-workspace.enzymedesign",
    "host.enzymedesign",
    "plugin-worker.enzymedesign",
    "process-runner.enzymedesign",
    "scheduler-runner.enzymedesign",
    "sqlite.enzymedesign",
    "ui.enzymedesign",
)


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _git(*arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", "-C", str(REPO_ROOT), *arguments),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        env={**os.environ, "LC_ALL": "C"},
    )
    if completed.returncode:
        raise QualifiedRuntimeCutoverError(
            "cutover_git_identity_failed",
            completed.stderr[-2000:].decode("utf-8", errors="replace"),
        )
    return completed.stdout


def _tree_closure(commit: str) -> str:
    entries = _git("ls-tree", "-r", commit, "--", *QUALIFIED_OWNER_PATHS)
    return canonical_sha256_digest(
        {
            "schema_version": "enzymedesign_qualified_owner_closure@1",
            "paths": list(QUALIFIED_OWNER_PATHS),
            "git_tree_entries": entries.decode("utf-8").splitlines(),
        }
    )


def _source_compatibility() -> QualificationSourceCompatibilityProof:
    deployment_source = collect_source_identity(REPO_ROOT)
    deployment_commit = deployment_source.commit
    changed = _git(
        "diff", "--name-only", "--no-renames", QUALIFICATION_COMMIT, deployment_commit
    ).decode("utf-8").splitlines()
    forbidden = sorted(
        path
        for path in changed
        if not any(
            path == prefix or path.startswith(prefix)
            for prefix in ALLOWED_CUTOVER_PREFIXES
        )
    )
    if forbidden:
        raise QualifiedRuntimeCutoverError(
            "cutover_source_diff_outside_allowlist",
            "deployment source changed outside cutover governance: "
            + ", ".join(forbidden),
        )
    packet = _load(PACKET_PATH)
    changed_status = _git(
        "diff", "--name-status", "--no-renames", QUALIFICATION_COMMIT, deployment_commit
    ).decode("utf-8").splitlines()
    return QualificationSourceCompatibilityProof.create(
        qualification_commit=QUALIFICATION_COMMIT,
        qualification_source_identity_digest=str(packet["source_identity_digest"]),
        deployment_commit=deployment_commit,
        deployment_source_identity_digest=deployment_source.digest,
        qualification_owner_closure_digest=_tree_closure(QUALIFICATION_COMMIT),
        deployment_owner_closure_digest=_tree_closure(deployment_commit),
        allowed_cutover_path_set_digest=canonical_sha256_digest(
            {"allowed_paths": list(ALLOWED_CUTOVER_PREFIXES)}
        ),
        diff_digest=canonical_sha256_digest(
            {"qualification_commit": QUALIFICATION_COMMIT, "changes": changed_status}
        ),
    )


def _read_report_digest(path: Path) -> str:
    payload = _load(path)
    digest = str(payload.get("report_digest"))
    computed_fields = {
        "report_digest",
        "qualified",
        "cutover",
        "occurrence_qualified",
    }
    identity = {
        key: value for key, value in payload.items() if key not in computed_fields
    }
    if digest != canonical_sha256_digest(identity):
        raise QualifiedRuntimeCutoverError(
            "cutover_qualification_report_digest_mismatch",
            f"{path.name} does not verify canonically",
        )
    return digest


def _verify_evidence(verified_at: str):
    return verify_batch_1_adoption_evidence(
        packet_path=PACKET_PATH,
        authorization_path=AUTHORIZATION_PATH,
        ledger_path=QUALIFICATION_LEDGER_PATH,
        receipt_set_path=RECEIPT_SET_PATH,
        operator_id=OPERATOR_ID,
        verified_at=verified_at,
    )


def _file_digest(path: Path) -> str:
    data = path.read_bytes()
    return canonical_sha256_digest({"bytes_hex": data.hex()})


def _backup_sources(state: ProtectedQualifiedRuntimeState) -> tuple[tuple[str, str], ...]:
    return (
        ("adoption-ledger", str(state.root / "adoption-ledger.json")),
        ("configuration", str(COMPOSITION_PATH)),
        ("qualification-receipts", str(RECEIPT_SET_PATH)),
        ("sqlite", str(state.root / "openzyme.sqlite3")),
        ("target-inventory", str(PACKET_PATH)),
        ("wheel-lock", str(REPO_ROOT / "uv.lock")),
    )


def _build_plan(state: ProtectedQualifiedRuntimeState) -> QualifiedRuntimeCutoverPlan:
    observed_at = _now()
    readiness, dry_plan, verified = _verify_evidence(observed_at)
    del readiness
    compatibility = _source_compatibility()
    composition = activate_enzymedesign_composition()
    quiescence = CutoverQuiescenceSeal.create(
        observations=tuple((writer, "not_installed") for writer in WRITERS),
        unsettled_effect_count=0,
        unknown_effect_count=0,
        sealed_at=observed_at,
    )
    return QualifiedRuntimeCutoverPlan.create(
        plan_id=f"cutover.enzymedesign.batch-1.{compatibility.deployment_commit[:12]}",
        operator_id=OPERATOR_ID,
        source_compatibility=compatibility,
        dry_plan_digest=dry_plan.dry_plan_digest,
        qualification_report_digest=_read_report_digest(QUALIFICATION_REPORT_PATH),
        receipt_set_report_digest=_read_report_digest(RECEIPT_SET_PATH),
        receipt_digests=tuple(
            item.receipt_digest for item in verified.selected_receipts
        ),
        deployment_inventory=(
            ("adapter-bundle", composition.adapter_bundle_digest),
            ("composition-document", composition.composition_document_digest),
            ("distribution", composition.distribution_manifest_digest),
            ("driver-bundle", composition.driver_bundle_digest),
            ("extension-bundle", composition.plugins.extension_bundle_digest),
            ("route-catalog", composition.route_catalog.catalog_digest),
            ("source-identity", compatibility.deployment_source_identity_digest),
            ("tool-catalog", composition.declared_tool_catalog.catalog_digest),
            ("wheel-lock", _file_digest(REPO_ROOT / "uv.lock")),
        ),
        backup_sources=_backup_sources(state),
        quiescence=quiescence,
        runtime_root=str(state.root),
        created_at=observed_at,
    )


def _proof_from(payload: Mapping[str, object]) -> QualificationSourceCompatibilityProof:
    return QualificationSourceCompatibilityProof.create(
        qualification_commit=str(payload["qualification_commit"]),
        qualification_source_identity_digest=str(
            payload["qualification_source_identity_digest"]
        ),
        deployment_commit=str(payload["deployment_commit"]),
        deployment_source_identity_digest=str(
            payload["deployment_source_identity_digest"]
        ),
        qualification_owner_closure_digest=str(
            payload["qualification_owner_closure_digest"]
        ),
        deployment_owner_closure_digest=str(payload["deployment_owner_closure_digest"]),
        allowed_cutover_path_set_digest=str(payload["allowed_cutover_path_set_digest"]),
        diff_digest=str(payload["diff_digest"]),
    )


def _quiescence_from(payload: Mapping[str, object]) -> CutoverQuiescenceSeal:
    observations = payload["observations"]
    if not isinstance(observations, list):
        raise ValueError("plan quiescence observations are invalid")
    return CutoverQuiescenceSeal.create(
        observations=tuple(
            (str(item["owner_id"]), str(item["state"]))
            for item in observations
            if isinstance(item, Mapping)
        ),
        unsettled_effect_count=int(payload["unsettled_effect_count"]),
        unknown_effect_count=int(payload["unknown_effect_count"]),
        sealed_at=str(payload["sealed_at"]),
    )


def _pairs(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be one object")
    return tuple((str(key), str(item)) for key, item in value.items())


def _plan_from(payload: Mapping[str, object]) -> QualifiedRuntimeCutoverPlan:
    source = payload["source_compatibility"]
    quiescence = payload["quiescence"]
    receipts = payload["receipt_digests"]
    if not isinstance(source, Mapping) or not isinstance(quiescence, Mapping):
        raise ValueError("cutover plan nested objects are invalid")
    if not isinstance(receipts, list):
        raise ValueError("cutover receipt digests are invalid")
    plan = QualifiedRuntimeCutoverPlan.create(
        plan_id=str(payload["plan_id"]),
        operator_id=str(payload["operator_id"]),
        source_compatibility=_proof_from(source),
        dry_plan_digest=str(payload["dry_plan_digest"]),
        qualification_report_digest=str(payload["qualification_report_digest"]),
        receipt_set_report_digest=str(payload["receipt_set_report_digest"]),
        receipt_digests=tuple(str(item) for item in receipts),
        deployment_inventory=_pairs(
            payload["deployment_inventory"], field_name="deployment_inventory"
        ),
        backup_sources=_pairs(payload["backup_sources"], field_name="backup_sources"),
        quiescence=_quiescence_from(quiescence),
        runtime_root=str(payload["runtime_root"]),
        created_at=str(payload["created_at"]),
    )
    if plan.to_dict() != dict(payload):
        raise QualifiedRuntimeCutoverError(
            "cutover_plan_persistence_drift", "persisted cutover plan is not canonical"
        )
    return plan


def _authority_from(payload: Mapping[str, object]) -> QualifiedRuntimeCutoverAuthority:
    authority = QualifiedRuntimeCutoverAuthority.create(
        authority_id=str(payload["authority_id"]),
        plan_digest=str(payload["plan_digest"]),
        deployment_source_identity_digest=str(
            payload["deployment_source_identity_digest"]
        ),
        operator_id=str(payload["operator_id"]),
        occurrence_id=str(payload["occurrence_id"]),
        authorized_at=str(payload["authorized_at"]),
    )
    if authority.to_dict() != dict(payload):
        raise QualifiedRuntimeCutoverError(
            "cutover_authority_persistence_drift",
            "persisted cutover authority is not canonical",
        )
    return authority


def _validate_current_source(plan: QualifiedRuntimeCutoverPlan) -> None:
    current = _source_compatibility()
    if current.to_dict() != plan.source_compatibility.to_dict():
        raise QualifiedRuntimeCutoverError(
            "cutover_deployment_source_drift",
            "current deployment source differs from the sealed plan",
        )


def _write_backup_file(path: Path, data: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _create_backups(
    state: ProtectedQualifiedRuntimeState,
    plan: QualifiedRuntimeCutoverPlan,
) -> dict[str, object]:
    sources = tuple((name, Path(path)) for name, path in plan.backup_sources)
    manifest = backup_manifest_payload(sources)
    backups = state.root / "backups"
    if backups.exists() or backups.is_symlink():
        metadata = backups.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise QualifiedRuntimeCutoverError(
                "cutover_backup_root_unsafe", "backup directory is unsafe"
            )
    else:
        backups.mkdir(mode=0o700, parents=False)
    for name, path in sources:
        destination = backups / f"{name}.backup"
        data = path.read_bytes() if path.exists() else b""
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != data:
                raise QualifiedRuntimeCutoverError(
                    "cutover_backup_residual_state",
                    f"backup residual state differs for {name}",
                )
        else:
            _write_backup_file(destination, data)
    state.write_once("backup-manifest", manifest)
    return manifest


def command_plan(state: ProtectedQualifiedRuntimeState) -> None:
    state.bootstrap()
    path = state.root / "plan.json"
    if path.exists():
        plan = _plan_from(state.read("plan"))
        _validate_current_source(plan)
    else:
        plan = _build_plan(state)
        state.write_once("plan", plan.to_dict())
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def command_authorize(state: ProtectedQualifiedRuntimeState) -> None:
    plan = _plan_from(state.read("plan"))
    _validate_current_source(plan)
    _verify_evidence(_now())
    path = state.root / "authority.json"
    if path.exists():
        authority = _authority_from(state.read("authority"))
    else:
        authority = QualifiedRuntimeCutoverAuthority.create(
            authority_id=f"authority.{plan.plan_id}",
            plan_digest=plan.plan_digest,
            deployment_source_identity_digest=(
                plan.source_compatibility.deployment_source_identity_digest
            ),
            operator_id=OPERATOR_ID,
            occurrence_id=(
                "occurrence.cutover.enzymedesign."
                + plan.source_compatibility.deployment_commit[:12]
            ),
            authorized_at=_now(),
        )
        state.write_once("authority", authority.to_dict())
    if authority.plan_digest != plan.plan_digest:
        raise QualifiedRuntimeCutoverError(
            "cutover_authority_plan_drift", "authority differs from the exact plan"
        )
    print(json.dumps(authority.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def command_apply(state: ProtectedQualifiedRuntimeState) -> None:
    if (state.root / "cutover-receipt.json").exists():
        print(json.dumps(state.read("cutover-receipt"), indent=2, sort_keys=True))
        return
    plan = _plan_from(state.read("plan"))
    authority = _authority_from(state.read("authority"))
    _validate_current_source(plan)
    readiness, _, verified = _verify_evidence(_now())
    if tuple(item.receipt_digest for item in verified.selected_receipts) != (
        plan.receipt_digests
    ):
        raise QualifiedRuntimeCutoverError(
            "cutover_pre_effect_receipt_drift",
            "current qualification receipt selection differs before effect",
        )
    manifest = _create_backups(state, plan)
    adopted_at = _now()
    ledger = build_adoption_ledger(
        readiness_plan=readiness,
        receipt_set=verified,
        plan=plan,
        authority=authority,
        adopted_at=adopted_at,
    )
    state.write_once("adoption-ledger", ledger.to_dict())
    ledger = load_adoption_ledger(
        payload=state.read("adoption-ledger"),
        plan=plan,
        authority=authority,
    )
    activation = {
        "schema_version": "enzymedesign_qualified_runtime_activation@1",
        "status": "active_pending_startup_readback",
        "plan_digest": plan.plan_digest,
        "authority_digest": authority.authority_digest,
        "adoption_ledger_digest": ledger.ledger_digest,
        "distribution_digest": dict(plan.deployment_inventory)["distribution"],
        "activated_at": adopted_at,
        "dual_write": False,
        "fallback_performed": False,
    }
    state.replace_exact("activation", activation, expected_prior_digest=None)
    admission = ledger.admission(readiness_plan=readiness, as_of=_now())
    if admission.blockers or len(admission.qualified_facts) != 44:
        raise QualifiedRuntimeCutoverError(
            "cutover_startup_admission_blocked",
            "isolated startup could not admit all 44 exact qualified facts",
        )
    composition = activate_enzymedesign_composition()
    if composition.distribution_manifest_digest != dict(plan.deployment_inventory)[
        "distribution"
    ]:
        raise QualifiedRuntimeCutoverError(
            "cutover_startup_distribution_drift",
            "startup composition differs from deployment inventory",
        )
    startup = CutoverStartupProof.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        adoption_ledger_digest=ledger.ledger_digest,
        distribution_digest=composition.distribution_manifest_digest,
        mounted_component_count=(
            len(composition.adapters)
            + len(composition.plugins.contributing_manifests)
            + len(composition.drivers)
        ),
        admitted_fact_count=len(admission.qualified_facts),
        verified_at=_now(),
    )
    state.write_once("startup-proof", startup.to_dict())
    active = {
        **activation,
        "status": "active",
        "startup_proof_digest": startup.proof_digest,
    }
    state.replace_exact(
        "activation",
        active,
        expected_prior_digest=canonical_sha256_digest(activation),
    )
    cutover = QualifiedRuntimeCutoverReceipt.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        adoption_ledger_digest=ledger.ledger_digest,
        startup_proof_digest=startup.proof_digest,
        backup_manifest_digest=str(manifest["manifest_digest"]),
        activated_at=_now(),
    )
    state.write_once("cutover-receipt", cutover.to_dict())
    monitoring = CutoverMonitoringSnapshot.create(
        cutover_receipt_digest=cutover.receipt_digest,
        activation_digest=canonical_sha256_digest(active),
        adoption_ledger_digest=ledger.ledger_digest,
        admitted_fact_count=44,
        status="healthy",
        diagnostic_ids=(),
        observed_at=_now(),
    )
    state.write_once("monitoring", monitoring.to_dict())
    print(json.dumps(cutover.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def _cutover_receipt(state: ProtectedQualifiedRuntimeState) -> dict[str, object]:
    payload = state.read("cutover-receipt")
    identity = {key: value for key, value in payload.items() if key != "receipt_digest"}
    if payload.get("receipt_digest") != canonical_sha256_digest(identity):
        raise QualifiedRuntimeCutoverError(
            "cutover_receipt_digest_mismatch", "cutover receipt integrity failed"
        )
    return payload


def _smoke_plan_from(payload: Mapping[str, object]) -> PostCutoverSmokePlan:
    plan = PostCutoverSmokePlan.create(
        plan_id=str(payload["plan_id"]),
        cutover_receipt_digest=str(payload["cutover_receipt_digest"]),
        adoption_ledger_digest=str(payload["adoption_ledger_digest"]),
        unit_digest=str(payload["unit_digest"]),
        route_id=str(payload["route_id"]),
        subject_id=str(payload["subject_id"]),
        created_at=str(payload["created_at"]),
    )
    if plan.to_dict() != dict(payload):
        raise QualifiedRuntimeCutoverError(
            "cutover_smoke_plan_drift", "persisted smoke plan is not canonical"
        )
    return plan


def command_smoke_plan(state: ProtectedQualifiedRuntimeState) -> None:
    cutover = _cutover_receipt(state)
    ledger = state.read("adoption-ledger")
    facts = ledger.get("facts")
    if not isinstance(facts, list):
        raise ValueError("adoption ledger facts are invalid")
    selected = next(
        (
            item
            for item in facts
            if isinstance(item, Mapping)
            and item.get("route_id")
            == "enzymedesign.bio-provider-http.uniprot.read@1"
            and item.get("operation") == "read-smoke"
        ),
        None,
    )
    if selected is None:
        raise QualifiedRuntimeCutoverError(
            "cutover_smoke_adopted_route_missing",
            "the exact adopted UniProt route is unavailable",
        )
    plan = PostCutoverSmokePlan.create(
        plan_id="smoke.enzymedesign.uniprot.batch-1",
        cutover_receipt_digest=str(cutover["receipt_digest"]),
        adoption_ledger_digest=str(ledger["ledger_digest"]),
        unit_digest=str(selected["unit_digest"]),
        route_id=str(selected["route_id"]),
        subject_id=str(selected["subject_id"]),
        created_at=_now(),
    )
    state.write_once("smoke-plan", plan.to_dict())
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def command_smoke_authorize(state: ProtectedQualifiedRuntimeState) -> None:
    plan = _smoke_plan_from(state.read("smoke-plan"))
    authority = PostCutoverSmokeAuthority.create(
        authority_id="authority.smoke.enzymedesign.uniprot.batch-1",
        plan_digest=plan.plan_digest,
        operator_id=OPERATOR_ID,
        occurrence_id="occurrence.smoke.enzymedesign.uniprot.batch-1",
        authorized_at=_now(),
    )
    state.write_once("smoke-authority", authority.to_dict())
    print(json.dumps(authority.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def command_smoke_apply(state: ProtectedQualifiedRuntimeState) -> None:
    if (state.root / "smoke-receipt.json").exists():
        print(json.dumps(state.read("smoke-receipt"), indent=2, sort_keys=True))
        return
    plan = _smoke_plan_from(state.read("smoke-plan"))
    authority_payload = state.read("smoke-authority")
    if authority_payload.get("plan_digest") != plan.plan_digest:
        raise QualifiedRuntimeCutoverError(
            "cutover_smoke_authority_drift", "smoke authority differs from plan"
        )
    authority_digest = str(authority_payload["authority_digest"])
    _verify_evidence(_now())
    activation = state.read("activation")
    if activation.get("status") != "active":
        raise QualifiedRuntimeCutoverError(
            "cutover_smoke_activation_missing", "qualified runtime is not active"
        )
    state.write_once(
        "smoke-dispatch",
        {
            "schema_version": "enzymedesign_post_cutover_smoke_dispatch@1",
            "plan_digest": plan.plan_digest,
            "authority_digest": authority_digest,
            "occurrence_id": str(authority_payload["occurrence_id"]),
            "dispatched_at": _now(),
            "max_retries": 0,
            "fallback_performed": False,
        },
    )
    result = HttpBioProviderAdapter().lookup_uniprot(accession="P69905")
    backend_receipt_digest = canonical_sha256_digest(
        {"provider_id": "uniprot", "result": asdict(result)}
    )
    receipt = PostCutoverSmokeReceipt.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority_digest,
        occurrence_id=str(authority_payload["occurrence_id"]),
        unit_digest=plan.unit_digest,
        backend_receipt_digest=backend_receipt_digest,
        effect_certainty="terminal_known",
        completed_at=_now(),
    )
    state.write_once("smoke-receipt", receipt.to_dict())
    first_live = FirstLiveBoundaryReceipt.create(
        cutover_receipt_digest=plan.cutover_receipt_digest,
        occurrence_id=receipt.occurrence_id,
        occurrence_authority_digest=authority_digest,
        effect_certainty=receipt.effect_certainty,
        accepted_at=_now(),
    )
    state.write_once("first-live", first_live.to_dict())
    state.write_once(
        "monitoring-live",
        {
            "schema_version": "enzymedesign_cutover_live_monitoring@1",
            "cutover_receipt_digest": plan.cutover_receipt_digest,
            "smoke_receipt_digest": receipt.receipt_digest,
            "first_live_receipt_digest": first_live.receipt_digest,
            "status": "healthy",
            "cleanup_required": False,
            "observed_at": _now(),
            "fallback_performed": False,
        },
    )
    print(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def command_rollback(state: ProtectedQualifiedRuntimeState) -> None:
    if (state.root / "first-live.json").exists():
        raise QualifiedRuntimeCutoverError(
            "cutover_rollback_after_first_live_forbidden",
            "rollback is forbidden after the forward-only first-live boundary",
        )
    plan = _plan_from(state.read("plan"))
    authority = _authority_from(state.read("authority"))
    activation = state.read("activation")
    prior_digest = canonical_sha256_digest(activation)
    manifest = state.read("backup-manifest")
    inactive = {
        "schema_version": "enzymedesign_qualified_runtime_activation@1",
        "status": "inactive_restored",
        "restored_from_activation_digest": prior_digest,
        "restored_at": _now(),
        "fallback_performed": False,
    }
    state.replace_exact("activation", inactive, expected_prior_digest=prior_digest)
    receipt = CutoverRollbackReceipt.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        restored_backup_manifest_digest=str(manifest["manifest_digest"]),
        prior_activation_digest=prior_digest,
        reason_code="operator_requested_pre_first_live_rollback",
        rolled_back_at=_now(),
    )
    state.write_once("rollback-receipt", receipt.to_dict())
    print(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


def command_status(state: ProtectedQualifiedRuntimeState) -> None:
    state.bootstrap()
    names = (
        "plan",
        "authority",
        "backup-manifest",
        "adoption-ledger",
        "activation",
        "startup-proof",
        "cutover-receipt",
        "monitoring",
        "smoke-plan",
        "smoke-authority",
        "smoke-dispatch",
        "smoke-receipt",
        "first-live",
        "monitoring-live",
        "rollback-receipt",
    )
    records = {}
    for name in names:
        path = state.root / f"{name}.json"
        if path.exists():
            payload = state.read(name)
            records[name] = {
                "schema_version": payload.get("schema_version"),
                "digest": next(
                    (
                        payload[key]
                        for key in (
                            "receipt_digest",
                            "snapshot_digest",
                            "proof_digest",
                            "ledger_digest",
                            "authority_digest",
                            "plan_digest",
                            "manifest_digest",
                        )
                        if key in payload
                    ),
                    canonical_sha256_digest(payload),
                ),
                "status": payload.get("status"),
            }
    print(
        json.dumps(
            {
                "runtime_root": str(state.root),
                "records": records,
                "secret_material_present": False,
                "fallback_performed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "authorize",
            "apply",
            "status",
            "rollback",
            "smoke-plan",
            "smoke-authorize",
            "smoke-apply",
        ),
    )
    args = parser.parse_args(argv)
    state = ProtectedQualifiedRuntimeState()
    commands = {
        "plan": command_plan,
        "authorize": command_authorize,
        "apply": command_apply,
        "status": command_status,
        "rollback": command_rollback,
        "smoke-plan": command_smoke_plan,
        "smoke-authorize": command_smoke_authorize,
        "smoke-apply": command_smoke_apply,
    }
    try:
        commands[args.command](state)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_code": getattr(
                        exc, "code", getattr(exc, "error_code", "cutover_failed")
                    ),
                    "component": "enzymedesign.qualified-runtime-cutover",
                    "phase": args.command,
                    "effect_certainty": (
                        "dispatch_in_doubt"
                        if args.command == "smoke-apply"
                        and (state.root / "smoke-dispatch.json").exists()
                        and not (state.root / "smoke-receipt.json").exists()
                        else "no_effect"
                    ),
                    "mutation_applied": args.command in {"apply", "rollback", "smoke-apply"},
                    "fallback_performed": False,
                    "retry_performed": False,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
