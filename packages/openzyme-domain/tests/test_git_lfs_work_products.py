from dataclasses import replace

import pytest

from openzyme_domain import GitLfsBindingPolicy
from openzyme_domain import GitLfsClosureEntry
from openzyme_domain import GitLfsClosureManifest
from openzyme_domain import GitLfsClosureVerification
from openzyme_domain import GitLfsPathRepresentation
from openzyme_domain import GitLfsPathRule
from openzyme_domain import GitLfsPointer
from openzyme_domain import GitLfsPrivateReachabilityReceipt
from openzyme_domain import GitLfsRetentionClass


def _policy() -> GitLfsBindingPolicy:
    return GitLfsBindingPolicy.create(
        binding_id="binding_c5",
        binding_version=5,
        repository_id="repository_c5",
        lfs_service_id="lfs_c5",
        lfs_endpoint="https://git.internal/repositories/repository_c5.git/info/lfs",
        object_format="sha256",
        path_rules=(
            GitLfsPathRule(
                rule_id="models",
                pattern="models/**",
                representation=GitLfsPathRepresentation.LFS_REQUIRED,
            ),
        ),
        ordinary_blob_threshold_bytes=1024,
        max_object_bytes=4096,
        max_workspace_bytes=8192,
        max_repository_bytes=16_384,
        published_retention_class=GitLfsRetentionClass.PUBLISHED,
        private_retention_class=GitLfsRetentionClass.PRIVATE,
        private_retention_seconds=3600,
        policy_version="repository-policy-c5",
        created_at="2026-08-16T00:00:00+00:00",
        created_by="operator:c5",
    )


def test_git_lfs_policy_is_canonical_versioned_and_closed() -> None:
    policy = _policy()

    assert policy.rule_for_path("models/a.bin") is not None
    assert policy.rule_for_path("notes/a.txt") is None
    with pytest.raises(ValueError, match="digest"):
        replace(policy, ordinary_blob_threshold_bytes=2048)


def test_git_lfs_pointer_parser_accepts_only_canonical_sha256_grammar() -> None:
    oid = "a" * 64
    pointer = GitLfsPointer.parse(
        (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{oid}\n"
            "size 12\n"
        ).encode("ascii")
    )

    assert pointer == GitLfsPointer(oid=oid, size=12)
    assert GitLfsPointer.parse(pointer.to_bytes()) == pointer
    with pytest.raises(ValueError, match="closed grammar"):
        GitLfsPointer.parse(
            pointer.to_bytes() + b"ext-0-openzyme custom-pointer\n"
        )
    with pytest.raises(ValueError, match="canonical LF"):
        GitLfsPointer.parse(pointer.to_bytes().replace(b"\n", b"\r\n"))


def test_lfs_closure_digest_excludes_observation_time_but_binds_objects() -> None:
    values = {
        "binding_id": "binding_c5",
        "binding_version": 5,
        "repository_id": "repository_c5",
        "commit": "1" * 40,
        "tree": "2" * 40,
        "policy_digest": _policy().policy_digest,
        "lfs_endpoint_identity": "lfs:c5",
        "authorization_scope_digest": f"sha256:{'3' * 64}",
        "entries": (
            GitLfsClosureEntry(
                path="models/a.bin",
                mode="100644",
                pointer_blob_oid="4" * 40,
                lfs_oid="5" * 64,
                size_bytes=12,
                object_read_receipt_id="read_1",
            ),
        ),
    }
    first = GitLfsClosureManifest.create(
        **values,
        verified_at="2026-08-16T00:00:00+00:00",
    )
    second = GitLfsClosureManifest.create(
        **{
            **values,
            "entries": (
                replace(
                    values["entries"][0],
                    object_read_receipt_id="read_2",
                ),
            ),
        },
        verified_at="2026-08-16T00:01:00+00:00",
    )

    assert first.manifest_digest == second.manifest_digest
    changed = GitLfsClosureManifest.create(
        **{
            **values,
            "entries": (replace(values["entries"][0], size_bytes=13),),
        },
        verified_at="2026-08-16T00:02:00+00:00",
    )
    assert changed.manifest_digest != first.manifest_digest


def test_fresh_closure_verification_binds_current_object_read_receipts() -> None:
    manifest_digest = f"sha256:{'1' * 64}"
    values = {
        "verification_id": "verification_c5_1",
        "manifest_digest": manifest_digest,
        "binding_id": "binding_c5",
        "binding_version": 5,
        "repository_id": "repository_c5",
        "authorization_scope_digest": f"sha256:{'2' * 64}",
        "object_read_receipt_ids": ("read_c5_1",),
        "observed_at": "2026-08-16T00:03:00+00:00",
    }

    first = GitLfsClosureVerification.create(**values)
    second = GitLfsClosureVerification.create(
        **{
            **values,
            "verification_id": "verification_c5_2",
            "object_read_receipt_ids": ("read_c5_2",),
            "observed_at": "2026-08-16T00:04:00+00:00",
        }
    )

    assert first.manifest_digest == second.manifest_digest
    assert first.verification_digest != second.verification_digest


def test_private_reachability_receipt_is_generation_and_retirement_bound() -> None:
    receipt = GitLfsPrivateReachabilityReceipt.create(
        receipt_id="private_reachability_c5",
        binding_id="binding_c5",
        binding_version=5,
        repository_id="repository_c5",
        namespace_id="namespace_c5",
        workspace_generation=7,
        terminal_refs_digest=f"sha256:{'3' * 64}",
        terminal_commits_digest=f"sha256:{'4' * 64}",
        reachable_oids=("6" * 64, "5" * 64),
        retirement_receipt_id="retirement_c5",
        created_at="2026-08-16T00:05:00+00:00",
    )

    assert receipt.reachable_oids == ("5" * 64, "6" * 64)
    with pytest.raises(ValueError, match="digest"):
        replace(receipt, workspace_generation=8)
