from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_core import GitLfsClientEnvironment
from openzyme_core import GitLfsClientQualificationError
from openzyme_core import GitLfsNativeClientProbe
from openzyme_core import qualify_gitless_compute
from openzyme_core import qualify_native_git_lfs_client


DIGEST = "sha256:" + "a" * 64
NOW = "2026-08-17T01:00:00+00:00"


@pytest.mark.parametrize(
    "environment",
    (
        GitLfsClientEnvironment.PODMAN_AGENT,
        GitLfsClientEnvironment.HPC_LOGIN,
    ),
)
def test_native_git_lfs_qualification_requires_standard_client_contract(
    environment: GitLfsClientEnvironment,
) -> None:
    probe = GitLfsNativeClientProbe(
        environment=environment,
        immutable_environment_digest=DIGEST,
        git_version="git version 2.39.5",
        git_lfs_version="git-lfs/3.3.0 (GitHub; linux amd64; go 1.19.8)",
        batch_api_version="2",
        transfer="basic",
        endpoint_identity_digest=DIGEST,
        credential_persistence="forbidden",
        observed_at=NOW,
    )

    qualification = qualify_native_git_lfs_client(probe)

    assert qualification.environment is environment
    assert qualification.immutable_environment_digest == DIGEST
    assert qualification.endpoint_identity_digest == DIGEST
    assert qualification.qualification_digest.startswith("sha256:")
    with pytest.raises(
        GitLfsClientQualificationError,
        match="standard Batch API v2 basic transfer",
    ):
        qualify_native_git_lfs_client(replace(probe, transfer="custom"))
    with pytest.raises(
        GitLfsClientQualificationError,
        match="credential persistence",
    ):
        qualify_native_git_lfs_client(
            replace(probe, credential_persistence="allowed")
        )


def test_compute_qualification_is_gitless_credentialless_and_remote_dark() -> None:
    qualification = qualify_gitless_compute(
        immutable_compute_digest=DIGEST,
        git_present=False,
        git_lfs_present=False,
        repository_credential_present=False,
        internal_remote_reachable=False,
        observed_at=NOW,
    )

    assert qualification.git_present is False
    assert qualification.git_lfs_present is False
    assert qualification.repository_credential_present is False
    assert qualification.internal_remote_reachable is False
    for drift in (
        {"git_present": True},
        {"git_lfs_present": True},
        {"repository_credential_present": True},
        {"internal_remote_reachable": True},
    ):
        with pytest.raises(
            GitLfsClientQualificationError,
            match="Gitless, credential-free",
        ):
            qualify_gitless_compute(
                immutable_compute_digest=DIGEST,
                git_present=bool(drift.get("git_present", False)),
                git_lfs_present=bool(drift.get("git_lfs_present", False)),
                repository_credential_present=bool(
                    drift.get("repository_credential_present", False)
                ),
                internal_remote_reachable=bool(
                    drift.get("internal_remote_reachable", False)
                ),
                observed_at=NOW,
            )
