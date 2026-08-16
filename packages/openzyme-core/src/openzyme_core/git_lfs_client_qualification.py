from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re


GIT_LFS_CLIENT_QUALIFICATION_SCHEMA_VERSION = "git_lfs_client_qualification@1"
GITLESS_COMPUTE_QUALIFICATION_SCHEMA_VERSION = "gitless_compute_qualification@1"


class GitLfsClientEnvironment(StrEnum):
    PODMAN_AGENT = "podman_agent"
    HPC_LOGIN = "hpc_login"


class GitLfsClientQualificationError(RuntimeError):
    error_code = "git_lfs_client_qualification_failed"


@dataclass(frozen=True, slots=True)
class GitLfsNativeClientProbe:
    environment: GitLfsClientEnvironment
    immutable_environment_digest: str
    git_version: str
    git_lfs_version: str
    batch_api_version: str
    transfer: str
    endpoint_identity_digest: str
    credential_persistence: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class GitLfsClientQualification:
    environment: GitLfsClientEnvironment
    immutable_environment_digest: str
    git_version: str
    git_lfs_version: str
    endpoint_identity_digest: str
    qualified_at: str
    qualification_digest: str
    schema_version: str = GIT_LFS_CLIENT_QUALIFICATION_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class GitlessComputeQualification:
    immutable_compute_digest: str
    git_present: bool
    git_lfs_present: bool
    repository_credential_present: bool
    internal_remote_reachable: bool
    qualified_at: str
    qualification_digest: str
    schema_version: str = GITLESS_COMPUTE_QUALIFICATION_SCHEMA_VERSION


def qualify_native_git_lfs_client(
    probe: GitLfsNativeClientProbe,
) -> GitLfsClientQualification:
    if probe.environment not in {
        GitLfsClientEnvironment.PODMAN_AGENT,
        GitLfsClientEnvironment.HPC_LOGIN,
    }:
        raise GitLfsClientQualificationError("unsupported Git LFS client environment")
    for value, field_name in (
        (probe.immutable_environment_digest, "immutable_environment_digest"),
        (probe.endpoint_identity_digest, "endpoint_identity_digest"),
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise GitLfsClientQualificationError(f"{field_name} is not immutable")
    if re.fullmatch(r"git version [0-9]+\.[0-9]+(?:\.[0-9]+)?", probe.git_version) is None:
        raise GitLfsClientQualificationError("native Git version probe is invalid")
    if "git-lfs/" not in probe.git_lfs_version:
        raise GitLfsClientQualificationError("native git-lfs version probe is invalid")
    if probe.batch_api_version != "2" or probe.transfer != "basic":
        raise GitLfsClientQualificationError(
            "native client did not qualify the standard Batch API v2 basic transfer"
        )
    if probe.credential_persistence != "forbidden":
        raise GitLfsClientQualificationError(
            "native client environment permits repository credential persistence"
        )
    payload = {
        "schema_version": GIT_LFS_CLIENT_QUALIFICATION_SCHEMA_VERSION,
        "environment": probe.environment.value,
        "immutable_environment_digest": probe.immutable_environment_digest,
        "git_version": probe.git_version,
        "git_lfs_version": probe.git_lfs_version,
        "endpoint_identity_digest": probe.endpoint_identity_digest,
        "qualified_at": probe.observed_at,
    }
    return GitLfsClientQualification(
        environment=probe.environment,
        immutable_environment_digest=probe.immutable_environment_digest,
        git_version=probe.git_version,
        git_lfs_version=probe.git_lfs_version,
        endpoint_identity_digest=probe.endpoint_identity_digest,
        qualified_at=probe.observed_at,
        qualification_digest=_digest(payload),
    )


def qualify_gitless_compute(
    *,
    immutable_compute_digest: str,
    git_present: bool,
    git_lfs_present: bool,
    repository_credential_present: bool,
    internal_remote_reachable: bool,
    observed_at: str,
) -> GitlessComputeQualification:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", immutable_compute_digest) is None:
        raise GitLfsClientQualificationError("compute identity is not immutable")
    if any(
        (
            git_present,
            git_lfs_present,
            repository_credential_present,
            internal_remote_reachable,
        )
    ):
        raise GitLfsClientQualificationError(
            "compute must be Gitless, credential-free, and unable to reach the internal remote"
        )
    payload = {
        "schema_version": GITLESS_COMPUTE_QUALIFICATION_SCHEMA_VERSION,
        "immutable_compute_digest": immutable_compute_digest,
        "git_present": False,
        "git_lfs_present": False,
        "repository_credential_present": False,
        "internal_remote_reachable": False,
        "qualified_at": observed_at,
    }
    return GitlessComputeQualification(
        immutable_compute_digest=immutable_compute_digest,
        git_present=False,
        git_lfs_present=False,
        repository_credential_present=False,
        internal_remote_reachable=False,
        qualified_at=observed_at,
        qualification_digest=_digest(payload),
    )


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "GIT_LFS_CLIENT_QUALIFICATION_SCHEMA_VERSION",
    "GITLESS_COMPUTE_QUALIFICATION_SCHEMA_VERSION",
    "GitLfsClientEnvironment",
    "GitLfsClientQualification",
    "GitLfsClientQualificationError",
    "GitLfsNativeClientProbe",
    "GitlessComputeQualification",
    "qualify_gitless_compute",
    "qualify_native_git_lfs_client",
]
