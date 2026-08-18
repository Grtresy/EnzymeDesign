#!/usr/bin/env python3
"""Read-only verifier for the C1 project repository binding acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


OPERATOR_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = OPERATOR_DIR.parents[3]
CHANGE_ID = "establish-project-repository-bindings"
C0_CHANGE_ID = "supersede-aox-hmm-artifact-cutover"
C0_ACCEPTANCE_PATH = (
    REPOSITORY_ROOT
    / "openspec/changes/supersede-aox-hmm-artifact-cutover/operator/acceptance-receipt.json"
)
C1_TASKS_PATH = REPOSITORY_ROOT / "openspec/changes" / CHANGE_ID / "tasks.md"
ACCEPTANCE_REPOSITORY_PATH = (
    "openspec/changes/establish-project-repository-bindings/"
    "operator/acceptance-receipt.json"
)

DOCUMENTS: dict[str, tuple[str, str | None]] = {
    "baseline": ("implementation-baseline.json", "receipt_digest"),
    "policy": ("repository-policy-v1.json", None),
    "binding": ("local-development-binding.json", "canonical_digest"),
    "preflight": ("durable-root-preflight-receipt.json", "receipt_digest"),
    "standard_protocol": (
        "standard-protocol-implementation-receipt.json",
        "receipt_digest",
    ),
    "local_protocol": ("local-protocol-acceptance-receipt.json", "receipt_digest"),
    "restore": ("local-restore-rehearsal-receipt.json", "receipt_digest"),
    "acceptance": ("acceptance-receipt.json", "receipt_digest"),
}

SCHEMAS = {
    "baseline": "project_repository_binding_implementation_baseline@1",
    "policy": "repository_policy@1",
    "binding": "project_repository_binding@1",
    "preflight": "project_repository_durable_root_preflight@1",
    "standard_protocol": "project_repository_standard_protocol_implementation@1",
    "local_protocol": "project_repository_binding_local_protocol_acceptance@1",
    "restore": "repository_restore_rehearsal@1",
    "acceptance": "project_repository_binding_acceptance@1",
}

EXPECTED_FIELDS = {
    "baseline": {
        "schema_id",
        "change_id",
        "source_revision",
        "issued_at",
        "baseline",
        "focused_test_baseline",
        "openspec_artifact_digests",
        "source_files",
        "c0_acceptance",
        "successor_gate",
        "receipt_digest",
    },
    "policy": {
        "schema_version",
        "policy_version",
        "git_object_format",
        "git_protocol",
        "lfs_protocol",
        "ref_acl",
        "read_visibility",
        "credential_authority",
        "storage_fallbacks",
        "upstream_effect_authority",
    },
    "binding": {
        "schema_version",
        "binding_id",
        "project_id",
        "binding_version",
        "repository_id",
        "internal_git_service_id",
        "internal_git_endpoint",
        "lfs_service_id",
        "lfs_endpoint",
        "upstream_identity",
        "upstream_url",
        "object_format",
        "default_base_ref",
        "default_base_commit",
        "ref_namespace_policy",
        "repository_policy_version",
        "repository_policy_digest",
        "created_at",
        "created_by",
        "canonical_digest",
    },
    "preflight": {
        "schema_id",
        "receipt_id",
        "created_at",
        "created_by",
        "deployment_profile",
        "https_origin",
        "database_identity_digest",
        "preflight",
        "root_policy",
        "status",
        "receipt_digest",
    },
    "standard_protocol": {
        "schema_id",
        "change_id",
        "source_revision",
        "issued_at",
        "implementation",
        "durable_storage",
        "authority",
        "forbidden_fallbacks",
        "product_boundaries",
        "implementation_files",
        "test_files",
        "status",
        "receipt_digest",
    },
    "local_protocol": {
        "schema_id",
        "receipt_id",
        "created_at",
        "created_by",
        "acceptance_profile",
        "binding",
        "session_pin",
        "credential_authority",
        "native_protocol",
        "preflight_inventory_digest",
        "upstream_effects",
        "status",
        "receipt_digest",
    },
    "restore": {
        "schema_version",
        "receipt_id",
        "created_at",
        "created_by",
        "acceptance_profile",
        "rehearsal_class",
        "database_identity_digest",
        "rehearsal_root_digest",
        "source_state_digest",
        "restarted_state_digest",
        "restored_state_digest",
        "source_preflight_inventory_digest",
        "restarted_preflight_inventory_digest",
        "restored_preflight_inventory_digest",
        "backup_inventory_digest",
        "failure_domain_devices",
        "failure_domain_separated",
        "production_disaster_recovery_proven",
        "verified_properties",
        "not_verified",
        "status",
        "receipt_digest",
    },
    "acceptance": {
        "schema_id",
        "change_id",
        "source_revision",
        "c0_acceptance_receipt_digest",
        "implementation_baseline_digest",
        "durable_root_preflight_digest",
        "standard_protocol_implementation_digest",
        "local_protocol_acceptance_digest",
        "restore_rehearsal_digest",
        "implementation_snapshot",
        "schema",
        "configuration",
        "scope_audit",
        "focused_tests",
        "native_integration",
        "documentation",
        "forbidden_pattern_audit",
        "openspec_validation",
        "mainline_validation",
        "product_boundaries",
        "eligible_successor",
        "status",
        "issued_at",
        "receipt_digest",
    },
}

ALLOWED_SCOPE_PREFIXES = (
    ".env.example",
    "apps/openzyme-host-api/",
    "docs/OpenZyme架构设计.md",
    "docs/v3/",
    "packages/openzyme-core/",
    "packages/openzyme-domain/",
    "packages/openzyme-runtime/",
    "openspec/changes/establish-project-repository-bindings/",
    "scripts/test-resource-manifest.json",
    "scripts/test_gate/resource.py",
)

BASELINE_REVISION = "9b78ec6a883f90ec4239d113e9300098120f68bd"
MIGRATION_PATH = (
    "packages/openzyme-core/src/openzyme_core/migrations/"
    "038_v3_project_repository_bindings.sql"
)
FOCUSED_TEST_FILES = (
    "packages/openzyme-domain/tests/test_repository_bindings.py",
    "packages/openzyme-core/tests/test_migrations.py",
    "packages/openzyme-core/tests/test_repository_binding_repositories.py",
    "packages/openzyme-core/tests/test_repository_binding_service.py",
    "packages/openzyme-core/tests/test_repository_credentials.py",
    "packages/openzyme-core/tests/test_repository_retention.py",
    "packages/openzyme-core/tests/test_repository_storage.py",
    "packages/openzyme-runtime/tests/test_settings.py",
    "apps/openzyme-host-api/tests/test_repository_operations.py",
    "apps/openzyme-host-api/tests/test_repository_preflight_security.py",
    "apps/openzyme-host-api/tests/test_repository_runtime_pin.py",
    "apps/openzyme-host-api/tests/test_repository_transport.py",
    "openspec/changes/establish-project-repository-bindings/operator/"
    "test_verify_repository_binding.py",
)
DOCUMENTATION_PATHS = (
    "apps/openzyme-host-api/README.md",
    "docs/OpenZyme架构设计.md",
    "docs/v3/README.md",
    "docs/v3/01-target-architecture.md",
    "docs/v3/02-control-plane.md",
    "docs/v3/04-public-interfaces.md",
    "docs/v3/repository-service-operations.md",
)
MAINLINE_CONFIGURATION_PATHS = (
    "apps/openzyme-web-ui/package.json",
    "pyproject.toml",
    "pytest.ini",
    "scripts/check-mainline.sh",
    "scripts/check-v3-architecture-qualification.sh",
    "scripts/test-affected-scope-map.json",
    "scripts/test-gate.toml",
    "scripts/test-resource-manifest.json",
)
MAINLINE_LOCK_PATHS = (
    "apps/openzyme-web-ui/npm-shrinkwrap.json",
    "apps/openzyme-web-ui/package-lock.json",
    "apps/openzyme-web-ui/pnpm-lock.yaml",
    "apps/openzyme-web-ui/yarn.lock",
    "skills-lock.json",
    "uv.lock",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def load_document(name: str, *, required: bool = True) -> dict[str, Any] | None:
    filename, _ = DOCUMENTS[name]
    path = OPERATOR_DIR / filename
    if not path.exists():
        if required:
            raise ValueError(f"required operator document is missing: {filename}")
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"operator document must be a JSON object: {filename}")
    return value


def verify_document(name: str, value: dict[str, Any]) -> str:
    expected_fields = EXPECTED_FIELDS[name]
    actual_fields = set(value)
    if actual_fields != expected_fields:
        raise ValueError(
            f"{name} fields are not closed: "
            f"missing={sorted(expected_fields - actual_fields)}, "
            f"extra={sorted(actual_fields - expected_fields)}"
        )
    schema_field = (
        "schema_version" if name in {"policy", "binding", "restore"} else "schema_id"
    )
    if value[schema_field] != SCHEMAS[name]:
        raise ValueError(f"{name} schema identity is invalid")
    _, digest_field = DOCUMENTS[name]
    if digest_field is None:
        return digest_value(value)
    preimage = {key: item for key, item in value.items() if key != digest_field}
    actual_digest = digest_value(preimage)
    if value[digest_field] != actual_digest:
        raise ValueError(f"{name} canonical digest does not match")
    return actual_digest


def _git_output(*arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _git_file(revision: str, path: str) -> bytes:
    return _git_output("show", f"{revision}:{path}")


def working_tree_changed_paths() -> list[str]:
    tracked = subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            BASELINE_REVISION,
            "--",
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "ls-files",
            "--others",
            "--exclude-standard",
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return sorted(set(tracked + untracked))


def publication_revision(receipt: dict[str, Any]) -> str | None:
    commits = subprocess.run(
        (
            "git",
            "log",
            "--format=%H",
            "--diff-filter=A",
            "--",
            ACCEPTANCE_REPOSITORY_PATH,
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not commits:
        return None
    if len(commits) != 1:
        raise ValueError("C1 acceptance receipt has multiple publication commits")
    revision = commits[0]
    published = _git_file(revision, ACCEPTANCE_REPOSITORY_PATH)
    current = (OPERATOR_DIR / "acceptance-receipt.json").read_bytes()
    if published != current:
        raise ValueError("published C1 acceptance receipt was modified")
    if (
        not subprocess.run(
            (
                "git",
                "merge-base",
                "--is-ancestor",
                receipt["source_revision"],
                revision,
            ),
            cwd=REPOSITORY_ROOT,
            check=False,
        ).returncode
        == 0
    ):
        raise ValueError("C1 publication revision is not based on source revision")
    return revision


def changed_paths(receipt: dict[str, Any], revision: str | None) -> list[str]:
    if revision is None:
        return working_tree_changed_paths()
    return subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            receipt["source_revision"],
            revision,
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def snapshot_file_bytes(path: str, revision: str | None) -> bytes:
    if revision is None:
        return (REPOSITORY_ROOT / path).read_bytes()
    return _git_file(revision, path)


def _snapshot_file_identity(path: str, revision: str | None) -> dict[str, Any]:
    if revision is None:
        source = REPOSITORY_ROOT / path
        if not source.exists():
            return {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": None,
                "digest": None,
            }
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"mainline source identity is not a regular file: {path}")
        content = source.read_bytes()
        mode = stat.S_IMODE(source.stat().st_mode)
    else:
        tree_entry = (
            _git_output("ls-tree", revision, "--", path).decode("utf-8").strip()
        )
        if not tree_entry:
            return {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": None,
                "digest": None,
            }
        mode_text, object_kind, _ = tree_entry.split(maxsplit=2)
        if object_kind != "blob" or mode_text not in {"100644", "100755"}:
            raise ValueError(f"mainline source identity is not a regular file: {path}")
        content = _git_file(revision, path)
        mode = 0o755 if mode_text == "100755" else 0o644
    return {
        "path": path,
        "kind": "file",
        "mode": mode,
        "size": len(content),
        "digest": digest_bytes(content),
    }


def _verify_mainline_source_identity(
    receipt: dict[str, Any],
    *,
    revision: str | None,
    changed: list[str],
) -> None:
    mainline = receipt["mainline_validation"]
    source = mainline["source_identity"]
    if not isinstance(source, dict) or set(source) != {
        "commit",
        "tracked_diff_digest",
        "tracked_dirty_paths",
        "relevant_untracked_sources",
        "configurations",
        "locks",
        "toolchains",
    }:
        raise ValueError("C1 mainline source identity schema is not closed")
    if source["commit"] != BASELINE_REVISION:
        raise ValueError("C1 mainline source identity has the wrong baseline")
    if digest_value(source) != mainline["source_identity_digest"]:
        raise ValueError("C1 mainline source identity digest does not match")

    tracked_at_baseline = set(
        _git_output(
            "-c",
            "core.quotePath=false",
            "ls-tree",
            "-r",
            "--name-only",
            BASELINE_REVISION,
        )
        .decode("utf-8")
        .splitlines()
    )
    expected_tracked = sorted(path for path in changed if path in tracked_at_baseline)
    if source["tracked_dirty_paths"] != expected_tracked:
        raise ValueError("C1 mainline tracked source set drifted")
    expected_untracked = sorted(
        path
        for path in changed
        if path not in tracked_at_baseline and path != ACCEPTANCE_REPOSITORY_PATH
    )
    observed_untracked = [item["path"] for item in source["relevant_untracked_sources"]]
    if observed_untracked != expected_untracked:
        raise ValueError("C1 mainline untracked source set drifted")

    diff_arguments = [
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        BASELINE_REVISION,
    ]
    if revision is not None:
        diff_arguments.append(revision)
    diff_arguments.extend(("--", *expected_tracked))
    if digest_bytes(_git_output(*diff_arguments)) != source["tracked_diff_digest"]:
        raise ValueError("C1 mainline tracked diff digest drifted")

    for group in ("relevant_untracked_sources", "configurations", "locks"):
        entries = source[group]
        if not isinstance(entries, list):
            raise ValueError(f"C1 mainline {group} is not a list")
        paths = [item["path"] for item in entries]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError(f"C1 mainline {group} paths are not sorted and unique")
        for item in entries:
            published_identity = _snapshot_file_identity(item["path"], revision)
            if item == published_identity:
                continue
            if (
                revision is not None
                and group == "locks"
                and published_identity["kind"] == "missing"
                and _snapshot_file_identity(item["path"], BASELINE_REVISION)["kind"]
                == "missing"
            ):
                continue
            raise ValueError(f"C1 mainline source identity drift: {item['path']}")
    if tuple(item["path"] for item in source["configurations"]) != (
        MAINLINE_CONFIGURATION_PATHS
    ):
        raise ValueError("C1 mainline configuration identity set drifted")
    if tuple(item["path"] for item in source["locks"]) != MAINLINE_LOCK_PATHS:
        raise ValueError("C1 mainline lock identity set drifted")
    toolchains = source["toolchains"]
    if not isinstance(toolchains, list) or [
        item.get("name") for item in toolchains if isinstance(item, dict)
    ] != ["python", "node", "uv", "npm"]:
        raise ValueError("C1 mainline toolchain identity set drifted")
    for item in toolchains:
        if not isinstance(item, dict) or set(item) != {
            "name",
            "executable",
            "version",
            "available",
        }:
            raise ValueError("C1 mainline toolchain identity schema is not closed")
        if (
            not isinstance(item["available"], bool)
            or not isinstance(item["version"], str)
            or not item["version"]
            or (
                item["executable"] is not None
                and not isinstance(item["executable"], str)
            )
        ):
            raise ValueError("C1 mainline toolchain identity is invalid")


def verify_baseline(baseline: dict[str, Any], c0: dict[str, Any]) -> None:
    if baseline["change_id"] != CHANGE_ID:
        raise ValueError("implementation baseline change id is invalid")
    c0_repository_path = C0_ACCEPTANCE_PATH.relative_to(REPOSITORY_ROOT).as_posix()
    c0_publication_commits = subprocess.run(
        ("git", "log", "--format=%H", "--diff-filter=A", "--", c0_repository_path),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if c0_publication_commits != [baseline["source_revision"]]:
        raise ValueError("implementation baseline does not start at C0 publication")
    if (
        _git_file(baseline["source_revision"], c0_repository_path)
        != C0_ACCEPTANCE_PATH.read_bytes()
    ):
        raise ValueError("published C0 acceptance receipt was modified")
    c0_binding = baseline["c0_acceptance"]
    if c0_binding["receipt_digest"] != c0["receipt_digest"]:
        raise ValueError("implementation baseline C0 receipt binding does not match")
    if c0_binding["status"] != "passed" or c0["legacy_decision"] != "legacy_no_go":
        raise ValueError("C0 prerequisite did not preserve passed legacy NO-GO")
    for source in baseline["source_files"]:
        content = _git_file(baseline["source_revision"], source["path"])
        if digest_bytes(content) != source["sha256"]:
            raise ValueError(f"implementation baseline source drift: {source['path']}")
    for relative_path, expected in baseline["openspec_artifact_digests"].items():
        repository_path = f"openspec/changes/{CHANGE_ID}/{relative_path}"
        if (
            digest_bytes(_git_file(baseline["source_revision"], repository_path))
            != expected
        ):
            raise ValueError(f"implementation baseline OpenSpec drift: {relative_path}")
    gate = baseline["successor_gate"]
    if gate != {
        "c1_and_c2_may_be_implemented_independently": True,
        "c3_blocked_until": ["C1 acceptance", "C2 acceptance"],
        "c4_blocked_until": ["C3 acceptance"],
    }:
        raise ValueError("implementation baseline successor gate drifted")


def verify_policy_and_binding(
    policy: dict[str, Any],
    policy_digest: str,
    binding: dict[str, Any],
) -> None:
    if binding["repository_policy_digest"] != policy_digest:
        raise ValueError("binding does not bind the exact repository policy")
    if binding["repository_policy_version"] != policy["policy_version"]:
        raise ValueError("binding repository policy version does not match")
    if binding["object_format"] != policy["git_object_format"]:
        raise ValueError("binding object format does not match repository policy")
    expected_git = f"https://localhost:8443/repositories/{binding['repository_id']}.git"
    if binding["internal_git_endpoint"] != expected_git:
        raise ValueError("local binding Git endpoint is not canonical")
    if binding["lfs_endpoint"] != f"{expected_git}/info/lfs":
        raise ValueError("local binding LFS endpoint is not canonical")
    if binding["upstream_url"] == binding["internal_git_endpoint"]:
        raise ValueError("internal repository and upstream authority are not separated")
    if policy["storage_fallbacks"] != []:
        raise ValueError("repository policy permits a storage fallback")
    if policy["credential_authority"]["replay_failed_command"] is not False:
        raise ValueError("repository policy permits hidden command replay")
    if policy["upstream_effect_authority"] != "separate_controlled_external_operation":
        raise ValueError("repository policy merges upstream and internal authority")


def verify_preflight(
    preflight: dict[str, Any],
    binding: dict[str, Any],
    policy_digest: str,
) -> None:
    if preflight["status"] != "passed_for_local_development":
        raise ValueError("durable-root preflight did not pass for local development")
    database = preflight["preflight"].get("database")
    if not isinstance(database, dict) or set(database) != {
        "path_digest",
        "owner_uid",
        "owner_gid",
        "mode",
    }:
        raise ValueError("durable-root preflight database fact is not closed")
    if (
        database["mode"] != "0600"
        or database["path_digest"] != preflight["database_identity_digest"]
    ):
        raise ValueError("durable-root preflight database authority drifted")
    root_policy = preflight["root_policy"]
    if root_policy["owner_only_permissions"] is not True:
        raise ValueError("durable roots are not owner-only")
    if root_policy["writable_fsync_probe_passed"] is not True:
        raise ValueError("durable roots did not pass writable fsync probes")
    if root_policy["failure_domain_separated"] is not False:
        raise ValueError("local preflight falsely claims separated failure domains")
    if root_policy["production_disaster_recovery_proven"] is not False:
        raise ValueError("local preflight falsely claims production disaster recovery")
    facts = preflight["preflight"]["root_facts"]
    if len(facts) != 3 or len({item["path_digest"] for item in facts}) != 3:
        raise ValueError("durable-root identity set is incomplete or aliased")
    if len({item["device"] for item in facts}) != 1:
        raise ValueError("recorded local failure-domain facts unexpectedly changed")
    active = preflight["preflight"]["active_bindings"]
    if len(active) != 1:
        raise ValueError("preflight must bind one active local repository")
    expected = {
        "project_id": binding["project_id"],
        "binding_id": binding["binding_id"],
        "binding_version": binding["binding_version"],
        "repository_id": binding["repository_id"],
        "object_format": binding["object_format"],
        "base_commit": binding["default_base_commit"],
        "policy_digest": policy_digest,
    }
    if active[0] != expected:
        raise ValueError("preflight active binding identity does not match")


def verify_standard_protocol(receipt: dict[str, Any]) -> None:
    if receipt["change_id"] != CHANGE_ID or receipt["status"] != "passed":
        raise ValueError("standard protocol implementation receipt did not pass")
    if receipt["source_revision"] != BASELINE_REVISION:
        raise ValueError("standard protocol implementation baseline drifted")
    implementation = receipt["implementation"]
    if implementation != {
        "repository_backend": "host_owned_bare_repositories",
        "git": "smart_http_v2_over_https",
        "lfs": "batch_api_v2_basic_transfer",
        "transport_boundary": "independent_repository_tls_app",
        "git_protocol_header_forwarded": True,
        "server_side_ref_acl": "pre_receive_hook",
    }:
        raise ValueError("standard protocol implementation identity drifted")
    storage = receipt["durable_storage"]
    if storage != {
        "bare_git_root": "explicit_deployment_setting",
        "lfs_object_root": "explicit_deployment_setting",
        "backup_root": "explicit_deployment_setting",
        "atomic_lfs_promote": True,
        "read_after_write_verification": True,
    }:
        raise ValueError("standard protocol durable storage contract drifted")
    authority = receipt["authority"]
    if authority["git_lfs_shared_repository_identity"] is not True:
        raise ValueError("Git and LFS do not share repository identity")
    if authority["scoped_bearer_required"] is not True:
        raise ValueError("standard protocols do not require scoped bearer authority")
    if authority["upstream_is_separate_authority"] is not True:
        raise ValueError("upstream authority is not separated")
    if receipt["forbidden_fallbacks"] != {
        "agent_facing_custom_file_rpc": False,
        "ambient_checkout": False,
        "ambient_cwd": False,
        "ambient_remote": False,
        "local_directory_remote": False,
        "temporary_repository": False,
        "upstream_on_internal_failure": False,
    }:
        raise ValueError("standard protocol receipt permits a forbidden fallback")
    if receipt["product_boundaries"] != {
        "agent_clone_provisioning_implemented": False,
        "workspace_publication_implemented": False,
        "production_capability_lease_issuance_proven": False,
        "upstream_effects": 0,
    }:
        raise ValueError("standard protocol receipt crosses the C1 product boundary")


def verify_local_protocol(
    receipt: dict[str, Any],
    binding: dict[str, Any],
    preflight: dict[str, Any],
) -> None:
    if receipt["status"] != "passed" or receipt["upstream_effects"] != 0:
        raise ValueError(
            "local native protocol acceptance did not close at no upstream effect"
        )
    if receipt["binding"] != {
        "binding_id": binding["binding_id"],
        "binding_version": binding["binding_version"],
        "canonical_digest": binding["canonical_digest"],
        "repository_id": binding["repository_id"],
        "exact_base_commit": binding["default_base_commit"],
    }:
        raise ValueError("local protocol receipt binding identity does not match")
    pin = receipt["session_pin"]
    if (
        pin["binding_id"] != binding["binding_id"]
        or pin["binding_version"] != binding["binding_version"]
    ):
        raise ValueError("local protocol receipt session pin does not match")
    credential = receipt["credential_authority"]
    if set(credential) != {
        "credential_id",
        "lease_id",
        "lease_assertion_class",
        "production_capability_lease_issuance_proven",
        "namespace_id",
        "active_lease_hold_id",
        "active_lease_hold_released_at",
        "revoked_at",
        "token_recorded",
    }:
        raise ValueError("local protocol credential authority schema is not closed")
    if credential["lease_assertion_class"] != "c1_acceptance_only":
        raise ValueError(
            "local protocol receipt does not label its acceptance-only lease"
        )
    if credential["production_capability_lease_issuance_proven"] is not False:
        raise ValueError(
            "C1 local protocol receipt overclaims production lease issuance"
        )
    if credential["token_recorded"] is not False or not credential["revoked_at"]:
        raise ValueError("local protocol credential was recorded or not revoked")
    if (
        not credential["namespace_id"]
        or not credential["active_lease_hold_id"]
        or not credential["active_lease_hold_released_at"]
    ):
        raise ValueError("local protocol lease namespace hold was not released")
    native = receipt["native_protocol"]
    if set(native) != {
        "git",
        "lfs",
        "https_origin",
        "private_ref",
        "terminal_commit",
        "lfs_oid",
        "lfs_size",
        "dynamic_https_health_verified",
        "service_restart_verified",
        "released_lease_hold_write_rejected",
        "revoked_credential_rejected",
    }:
        raise ValueError("local protocol native evidence schema is not closed")
    if native["git"] != "smart_http_v2_over_https" or native["lfs"] != "batch_v2_basic":
        raise ValueError("local protocol receipt did not use standard Git/LFS")
    if native["service_restart_verified"] is not True:
        raise ValueError("local protocol receipt did not verify service restart")
    if native["dynamic_https_health_verified"] is not True:
        raise ValueError("local protocol receipt did not verify dynamic HTTPS health")
    if native["released_lease_hold_write_rejected"] is not True:
        raise ValueError(
            "local protocol receipt did not reject write after lease hold release"
        )
    if native["revoked_credential_rejected"] is not True:
        raise ValueError("local protocol receipt did not reject revoked authority")
    if (
        receipt["preflight_inventory_digest"]
        != preflight["preflight"]["inventory_digest"]
    ):
        raise ValueError("local protocol receipt does not bind durable-root preflight")


def verify_restore(receipt: dict[str, Any], preflight: dict[str, Any]) -> None:
    if receipt["status"] != "passed_for_local_development":
        raise ValueError("local restore rehearsal did not pass")
    if receipt["rehearsal_class"] != "local_same_filesystem_logical_restore":
        raise ValueError("local restore rehearsal class is invalid")
    if receipt["failure_domain_separated"] is not False:
        raise ValueError(
            "local restore rehearsal falsely claims failure-domain separation"
        )
    if receipt["production_disaster_recovery_proven"] is not False:
        raise ValueError(
            "local restore rehearsal falsely claims production disaster recovery"
        )
    if len(set(receipt["failure_domain_devices"].values())) != 1:
        raise ValueError("local restore rehearsal device facts unexpectedly changed")
    if (
        len(
            {
                receipt["source_state_digest"],
                receipt["restarted_state_digest"],
                receipt["restored_state_digest"],
            }
        )
        != 1
    ):
        raise ValueError("restart or restore changed repository service state")
    inventory = preflight["preflight"]["inventory_digest"]
    if {
        receipt["source_preflight_inventory_digest"],
        receipt["restarted_preflight_inventory_digest"],
        receipt["restored_preflight_inventory_digest"],
    } != {inventory}:
        raise ValueError("restart or restore changed binding inventory")
    required_not_verified = {
        "filesystem_loss_survival",
        "host_loss_survival",
        "offsite_disaster_recovery",
        "production_rpo_rto",
    }
    if set(receipt["not_verified"]) != required_not_verified:
        raise ValueError("local restore receipt does not disclose production limits")


def verify_tasks() -> int:
    text = C1_TASKS_PATH.read_text(encoding="utf-8")
    complete = re.findall(r"^- \[x\] (\d+\.\d+) ", text, flags=re.MULTILINE)
    pending = re.findall(r"^- \[ \] (\d+\.\d+) ", text, flags=re.MULTILINE)
    if pending:
        raise ValueError(f"C1 task checklist remains incomplete: {pending}")
    if len(complete) != 40 or len(complete) != len(set(complete)):
        raise ValueError("C1 task checklist is incomplete or duplicated")
    return len(complete)


def verify_snapshot(
    receipt: dict[str, Any],
    standard_protocol: dict[str, Any],
) -> str | None:
    revision = publication_revision(receipt)
    paths = changed_paths(receipt, revision)
    forbidden = [
        path
        for path in paths
        if not any(
            path == prefix or path.startswith(prefix)
            for prefix in ALLOWED_SCOPE_PREFIXES
        )
    ]
    if forbidden:
        raise ValueError(f"C1 changed forbidden paths: {forbidden}")
    _verify_mainline_source_identity(receipt, revision=revision, changed=paths)
    audit = receipt["scope_audit"]
    if audit["status"] != "passed":
        raise ValueError("C1 scope audit did not pass")
    if audit["changed_path_count"] != len(paths):
        raise ValueError("C1 scope audit path count does not match")
    if audit["changed_path_set_digest"] != digest_value(paths):
        raise ValueError("C1 scope audit path digest does not match")
    if audit["forbidden_changed_paths"] != []:
        raise ValueError("C1 scope audit reports forbidden paths")

    snapshot = receipt["implementation_snapshot"]
    entries = snapshot["files"]
    if snapshot["file_count"] != len(entries):
        raise ValueError("C1 implementation snapshot count does not match")
    if snapshot["tree_digest"] != digest_value(entries):
        raise ValueError("C1 implementation snapshot digest does not match")
    manifest_paths = [entry["path"] for entry in entries]
    if manifest_paths != sorted(manifest_paths) or len(manifest_paths) != len(
        set(manifest_paths)
    ):
        raise ValueError("C1 implementation snapshot paths are not sorted and unique")
    if sorted([*manifest_paths, ACCEPTANCE_REPOSITORY_PATH]) != paths:
        raise ValueError(
            "C1 implementation snapshot does not cover the exact change scope"
        )
    for entry in entries:
        content = snapshot_file_bytes(entry["path"], revision)
        if digest_bytes(content) != entry["sha256"] or len(content) != entry["size"]:
            raise ValueError(f"C1 implementation snapshot drift: {entry['path']}")
    for entry in standard_protocol["implementation_files"]:
        content = snapshot_file_bytes(entry["path"], revision)
        if digest_bytes(content) != entry["sha256"] or len(content) != entry["size"]:
            raise ValueError(
                f"standard protocol implementation source drift: {entry['path']}"
            )
    for path in standard_protocol["test_files"]:
        snapshot_file_bytes(path, revision)
    return revision


def verify_acceptance(
    receipt: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    document_digests: dict[str, str],
) -> None:
    expected_bindings = {
        "c0_acceptance_receipt_digest": documents["c0"]["receipt_digest"],
        "implementation_baseline_digest": document_digests["baseline"],
        "durable_root_preflight_digest": document_digests["preflight"],
        "standard_protocol_implementation_digest": document_digests[
            "standard_protocol"
        ],
        "local_protocol_acceptance_digest": document_digests["local_protocol"],
        "restore_rehearsal_digest": document_digests["restore"],
    }
    for field, expected in expected_bindings.items():
        if receipt[field] != expected:
            raise ValueError(f"C1 acceptance {field} binding does not match")
    if receipt["change_id"] != CHANGE_ID or receipt["status"] != "passed":
        raise ValueError("C1 acceptance receipt did not pass")
    if receipt["source_revision"] != BASELINE_REVISION:
        raise ValueError("C1 acceptance source revision is not the C0 baseline")

    acceptance_revision = publication_revision(receipt)
    if acceptance_revision is None:
        raise ValueError("C1 acceptance receipt has no publication revision")
    expected_schema = {
        "sqlite_schema_before": 37,
        "sqlite_schema_after": 38,
        "migration_id": "038_v3_project_repository_bindings",
        "migration_sha256": digest_bytes(
            _git_file(acceptance_revision, MIGRATION_PATH)
        ),
        "binding_schema": "project_repository_binding@1",
        "session_pin_schema": "session_repository_binding_pin@1",
        "credential_schema": "repository_credential@1",
    }
    if receipt["schema"] != expected_schema:
        raise ValueError("C1 acceptance schema identity or migration digest drifted")

    preflight = documents["preflight"]
    binding = documents["binding"]
    root_facts = preflight["preflight"]["root_facts"]
    database = preflight["preflight"]["database"]
    expected_configuration = {
        "acceptance_profile": "approved_local_development",
        "https_origin": preflight["https_origin"],
        "database_identity_digest": preflight["database_identity_digest"],
        "database_mode": database["mode"],
        "binding_inventory_digest": preflight["preflight"]["inventory_digest"],
        "repository_policy_digest": document_digests["policy"],
        "binding_canonical_digest": binding["canonical_digest"],
        "durable_root_path_digests": sorted(
            str(item["path_digest"]) for item in root_facts
        ),
        "all_required_settings_explicit": True,
        "credential_material_projected": False,
        "upstream_authority": "separate_controlled_external_operation",
    }
    if receipt["configuration"] != expected_configuration:
        raise ValueError("C1 acceptance deployment configuration binding drifted")
    if database["mode"] != "0600":
        raise ValueError("C1 acceptance control-plane database is not owner-only")

    focused = receipt["focused_tests"]
    if set(focused) != {"status", "test_files", "passed", "failed"}:
        raise ValueError("C1 focused-test evidence schema is not closed")
    if (
        focused["status"] != "passed"
        or tuple(focused["test_files"]) != FOCUSED_TEST_FILES
        or not isinstance(focused["passed"], int)
        or isinstance(focused["passed"], bool)
        or focused["passed"] <= 0
        or focused["failed"] != 0
    ):
        raise ValueError("C1 focused tests did not close the exact test scope")

    native = receipt["native_integration"]
    if set(native) != {
        "status",
        "test_file",
        "passed",
        "failed",
        "git_smart_http_v2_over_https",
        "git_lfs_batch_v2_basic",
        "durable_restart_reread",
        "revoked_credential_rejected",
        "hostile_git_environment_isolated",
        "multi_ref_push_rejected",
        "dynamic_health_verified",
        "closed_namespace_write_rejected",
        "released_lease_hold_write_rejected",
    }:
        raise ValueError("C1 native-integration evidence schema is not closed")
    if native != {
        "status": "passed",
        "test_file": ("apps/openzyme-host-api/tests/test_repository_native_clients.py"),
        "passed": 3,
        "failed": 0,
        "git_smart_http_v2_over_https": True,
        "git_lfs_batch_v2_basic": True,
        "durable_restart_reread": True,
        "revoked_credential_rejected": True,
        "hostile_git_environment_isolated": True,
        "multi_ref_push_rejected": True,
        "dynamic_health_verified": True,
        "closed_namespace_write_rejected": True,
        "released_lease_hold_write_rejected": True,
    }:
        raise ValueError("C1 native Git/LFS integration proof is incomplete")

    documentation = receipt["documentation"]
    if documentation != {
        "status": "passed",
        "paths": list(DOCUMENTATION_PATHS),
    }:
        raise ValueError("C1 architecture and operations documentation is incomplete")

    forbidden = receipt["forbidden_pattern_audit"]
    if forbidden != {
        "status": "passed",
        "catch_all_matches": [],
        "silent_fallback_matches": [],
        "ambient_git_fallback_matches": [],
    }:
        raise ValueError("C1 forbidden-pattern audit did not close cleanly")

    openspec = receipt["openspec_validation"]
    if openspec != {
        "status": "passed",
        "command": (
            "DO_NOT_TRACK=1 openspec validate "
            "establish-project-repository-bindings --type change --strict "
            "--no-interactive"
        ),
    }:
        raise ValueError("C1 strict OpenSpec validation evidence drifted")

    mainline = receipt["mainline_validation"]
    if set(mainline) != {
        "status",
        "command",
        "verification_command",
        "profile_id",
        "authority_domain",
        "current_authoritative_entry",
        "plan_digest",
        "receipt_digest",
        "source_identity_digest",
        "source_identity",
        "plan_schema_id",
        "receipt_schema_id",
        "receipt_plan_digest",
        "receipt_source_identity_digest",
        "verification_result",
        "plan",
        "receipt",
        "terminal_status",
        "authoritative",
        "profile_contract_authoritative",
        "admission_eligible",
        "live_eligible",
        "verified_current_sources",
    }:
        raise ValueError("C1 mainline evidence schema is not closed")
    expected_mainline = {
        "status": "passed",
        "command": "./scripts/check-mainline.sh",
        "verification_command": "verify-mainline-authoritative",
        "profile_id": "mainline_authoritative",
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
        "terminal_status": "pass",
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "verified_current_sources": True,
        "plan_schema_id": "openzyme_test_execution_plan@1",
        "receipt_schema_id": "openzyme_test_gate_receipt@1",
    }
    for field, expected in expected_mainline.items():
        if mainline[field] != expected:
            raise ValueError(f"C1 mainline authority drifted: {field}")
    for field in ("plan_digest", "receipt_digest", "source_identity_digest"):
        value = mainline[field]
        if (
            not isinstance(value, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
        ):
            raise ValueError(f"C1 mainline {field} is not a canonical digest")
    if mainline["receipt_plan_digest"] != mainline["plan_digest"]:
        raise ValueError("C1 mainline receipt does not bind the exact plan")
    if mainline["receipt_source_identity_digest"] != mainline["source_identity_digest"]:
        raise ValueError("C1 mainline receipt source identity drifted")
    verification_result = mainline["verification_result"]
    if not isinstance(verification_result, dict) or verification_result != {
        "profile_id": "mainline_authoritative",
        "output_root": verification_result.get("output_root"),
        "plan_digest": mainline["plan_digest"],
        "receipt_digest": mainline["receipt_digest"],
        "terminal_status": "pass",
        "valid": True,
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
    }:
        raise ValueError("C1 official mainline verification result drifted")
    output_root = verification_result["output_root"]
    if not isinstance(output_root, str) or not Path(output_root).is_absolute():
        raise ValueError("C1 official mainline output root is invalid")

    plan = mainline["plan"]
    if not isinstance(plan, dict) or set(plan) != {
        "authority",
        "collections",
        "config_digest",
        "expected_coverage_digest",
        "invocation_id",
        "legacy_execution_multiset_digest",
        "node_ownership",
        "output_root",
        "planner_digest",
        "profile_id",
        "schema_id",
        "self_digest",
        "source_identity",
        "source_recheck_policy",
        "stages",
        "toolchains",
        "worker_policy",
    }:
        raise ValueError("C1 authoritative mainline plan schema is not closed")
    plan_preimage = {key: value for key, value in plan.items() if key != "self_digest"}
    if plan["self_digest"] != digest_value(plan_preimage):
        raise ValueError("C1 authoritative mainline plan seal is invalid")
    if (
        plan["self_digest"] != mainline["plan_digest"]
        or plan["schema_id"] != mainline["plan_schema_id"]
        or plan["profile_id"] != "mainline_authoritative"
        or plan["source_identity"] != mainline["source_identity"]
        or plan["toolchains"] != mainline["source_identity"]["toolchains"]
        or plan["output_root"] != output_root
    ):
        raise ValueError("C1 authoritative mainline plan binding drifted")
    if plan["authority"] != {
        "admission_eligible": False,
        "authoritative": True,
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
        "live_eligible": False,
        "profile_contract_authoritative": True,
    }:
        raise ValueError("C1 authoritative mainline plan authority drifted")

    mainline_receipt = mainline["receipt"]
    if not isinstance(mainline_receipt, dict) or set(mainline_receipt) != {
        "admission_eligible",
        "authoritative",
        "coverage",
        "frontend",
        "invocation_id",
        "live_eligible",
        "plan_digest",
        "profile_id",
        "qualification",
        "resource_assignments",
        "schema_id",
        "self_digest",
        "source_identity_digest",
        "stages",
        "terminal_status",
        "timing",
    }:
        raise ValueError("C1 authoritative mainline receipt schema is not closed")
    receipt_preimage = {
        key: value for key, value in mainline_receipt.items() if key != "self_digest"
    }
    if mainline_receipt["self_digest"] != digest_value(receipt_preimage):
        raise ValueError("C1 authoritative mainline receipt seal is invalid")
    if mainline_receipt != {
        **mainline_receipt,
        "schema_id": mainline["receipt_schema_id"],
        "self_digest": mainline["receipt_digest"],
        "plan_digest": mainline["plan_digest"],
        "source_identity_digest": mainline["source_identity_digest"],
        "profile_id": "mainline_authoritative",
        "terminal_status": "pass",
        "authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
    }:
        raise ValueError("C1 authoritative mainline receipt binding drifted")
    if receipt["product_boundaries"] != {
        "agent_clone_provisioning_implemented": False,
        "workspace_publication_implemented": False,
        "production_capability_lease_issuance_proven": False,
        "production_disaster_recovery_proven": False,
        "upstream_effects": 0,
    }:
        raise ValueError("C1 acceptance crosses or overclaims its product boundary")
    if receipt["eligible_successor"] != {
        "change": "provision-independent-agent-git-workspaces",
        "condition": "establish-agent-capability-leases acceptance also passes",
        "eligible_now": False,
    }:
        raise ValueError("C1 acceptance successor condition drifted")


def load_c0_acceptance() -> dict[str, Any]:
    value = json.loads(C0_ACCEPTANCE_PATH.read_text(encoding="utf-8"))
    if value["schema_id"] != "aox_artifact_cutover_supersession_acceptance@1":
        raise ValueError("C0 acceptance schema identity is invalid")
    preimage = {key: item for key, item in value.items() if key != "receipt_digest"}
    if value["receipt_digest"] != digest_value(preimage):
        raise ValueError("C0 acceptance canonical digest does not match")
    if value["change_id"] != C0_CHANGE_ID or value["status"] != "passed":
        raise ValueError("C0 acceptance prerequisite did not pass")
    return value


def verify_all(
    *,
    require_acceptance: bool,
    verify_sources: bool,
) -> dict[str, Any]:
    if require_acceptance and not verify_sources:
        raise ValueError("final C1 acceptance requires current source verification")
    names = [
        "baseline",
        "policy",
        "binding",
        "preflight",
        "standard_protocol",
        "local_protocol",
        "restore",
    ]
    if require_acceptance:
        names.append("acceptance")
    loaded = {name: load_document(name) for name in names}
    documents = {name: value for name, value in loaded.items() if value is not None}
    digests = {name: verify_document(name, value) for name, value in documents.items()}
    c0 = load_c0_acceptance()
    documents["c0"] = c0
    verify_baseline(documents["baseline"], c0)
    verify_policy_and_binding(
        documents["policy"],
        digests["policy"],
        documents["binding"],
    )
    verify_preflight(documents["preflight"], documents["binding"], digests["policy"])
    verify_standard_protocol(documents["standard_protocol"])
    verify_local_protocol(
        documents["local_protocol"],
        documents["binding"],
        documents["preflight"],
    )
    verify_restore(documents["restore"], documents["preflight"])
    completed_tasks = verify_tasks() if require_acceptance else 0
    publication = None
    if require_acceptance:
        verify_acceptance(documents["acceptance"], documents, digests)
        if verify_sources:
            publication = verify_snapshot(
                documents["acceptance"],
                documents["standard_protocol"],
            )
    return {
        "schema_id": "project_repository_binding_verification@1",
        "status": "passed",
        "acceptance_required": require_acceptance,
        "sources_verified": verify_sources,
        "publication_revision": publication,
        "completed_tasks": completed_tasks,
        "document_digests": digests,
        "upstream_effects": 0,
        "production_capability_lease_issuance_proven": False,
        "production_disaster_recovery_proven": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-acceptance",
        action="store_true",
        help="also require and verify the final C1 acceptance receipt",
    )
    parser.add_argument(
        "--verify-current-sources",
        action="store_true",
        help="verify the exact working or published C1 implementation snapshot",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    if arguments.verify_current_sources and not arguments.require_acceptance:
        raise ValueError("source verification requires the final acceptance receipt")
    result = verify_all(
        require_acceptance=arguments.require_acceptance,
        verify_sources=arguments.verify_current_sources,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
