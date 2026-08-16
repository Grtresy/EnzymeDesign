from __future__ import annotations

from dataclasses import dataclass

from openzyme_domain import RevisionPathEntryKind

from .agent_capsule_runtime import AgentCapsuleRuntimeService
from .agent_capsule_runtime import AgentProcessCredentialRequest
from .repositories import CoreRepositories
from .revision_path_handoffs import RevisionPathReferenceService


class NativeRevisionPathFetchError(RuntimeError):
    error_code = "native_revision_path_fetch_failed"


@dataclass(frozen=True, slots=True)
class NativeRevisionPathFetchResult:
    handoff_id: str
    publication_id: str
    commit: str
    tree: str
    verified_ref_ids: tuple[str, ...]
    git_process_digest: str
    lfs_process_digest: str | None
    checkout_performed: bool = False
    merge_performed: bool = False
    task_transition_performed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "native_revision_path_fetch_result@1",
            "handoff_id": self.handoff_id,
            "publication_id": self.publication_id,
            "commit": self.commit,
            "tree": self.tree,
            "verified_ref_ids": list(self.verified_ref_ids),
            "git_process_digest": self.git_process_digest,
            "lfs_process_digest": self.lfs_process_digest,
            "checkout_performed": self.checkout_performed,
            "merge_performed": self.merge_performed,
            "task_transition_performed": self.task_transition_performed,
        }


_GIT_VERIFY_SCRIPT = r"""
set -euo pipefail
publication_ref="$1"
publication_id="$2"
expected_commit="$3"
expected_tree="$4"
shift 4
inspection_ref="refs/openzyme/fetched/${publication_id}"
git fetch --no-tags origin "${publication_ref}:${inspection_ref}"
observed_commit="$(git rev-parse --verify "${inspection_ref}^{commit}")"
observed_tree="$(git rev-parse --verify "${inspection_ref}^{tree}")"
test "${observed_commit}" = "${expected_commit}"
test "${observed_tree}" = "${expected_tree}"
while test "$#" -gt 0; do
    ref_id="$1"
    path="$2"
    entry_kind="$3"
    expected_object="$4"
    expected_size="$5"
    shift 5
    observed_object="$(git rev-parse --verify "${expected_commit}:${path}")"
    test "${observed_object}" = "${expected_object}"
    if test "${entry_kind}" = "directory"; then
        test "$(git cat-file -t "${observed_object}")" = "tree"
    elif test "${entry_kind}" != "gitlink"; then
        test "$(git cat-file -t "${observed_object}")" = "blob"
        test "$(git cat-file -s "${observed_object}")" = "${expected_size}"
    fi
    printf 'OPENZYME_GIT_REF=%s\n' "${ref_id}"
done
printf 'OPENZYME_PUBLICATION=%s\n' "${publication_id}"
printf 'OPENZYME_COMMIT=%s\n' "${observed_commit}"
printf 'OPENZYME_TREE=%s\n' "${observed_tree}"
""".strip()


_LFS_VERIFY_SCRIPT = r"""
set -euo pipefail
publication_ref="$1"
shift
git lfs fetch origin "${publication_ref}"
while test "$#" -gt 0; do
    ref_id="$1"
    commit="$2"
    path="$3"
    expected_object="$4"
    expected_lfs_oid="$5"
    expected_lfs_size="$6"
    shift 6
    observed_object="$(git rev-parse --verify "${commit}:${path}")"
    test "${observed_object}" = "${expected_object}"
    tmp_file="$(mktemp /tmp/openzyme-lfs-verify.XXXXXX)"
    trap 'rm -f "${tmp_file}"' EXIT
    git cat-file blob "${observed_object}" | git lfs smudge >"${tmp_file}"
    test "$(wc -c <"${tmp_file}")" = "${expected_lfs_size}"
    test "sha256:$(sha256sum "${tmp_file}" | cut -d' ' -f1)" = "${expected_lfs_oid}"
    rm -f "${tmp_file}"
    trap - EXIT
    printf 'OPENZYME_LFS_REF=%s\n' "${ref_id}"
done
""".strip()


@dataclass(slots=True)
class NativeRevisionPathFetchService:
    repositories: CoreRepositories
    runtime: AgentCapsuleRuntimeService

    def fetch_handoff_publication(
        self,
        *,
        session_id: str,
        agent_id: str,
        handoff_id: str,
        publication_id: str,
    ) -> NativeRevisionPathFetchResult:
        handoff = self.repositories.revision_path_handoffs.get_handoff(handoff_id)
        if handoff is None or handoff.session_id != session_id:
            raise NativeRevisionPathFetchError(
                "file handoff does not belong to the current session"
            )
        if handoff.recipient_agent_id != agent_id:
            raise NativeRevisionPathFetchError(
                "only the exact handoff recipient may fetch its publication"
            )
        revision = self.repositories.published_revisions.get(publication_id)
        if revision is None or revision.session_id != session_id:
            raise NativeRevisionPathFetchError(
                "handoff publication is not canonical in the current session"
            )
        selected = tuple(
            entry for entry in handoff.entries if entry.publication_id == publication_id
        )
        if not selected:
            raise NativeRevisionPathFetchError(
                "handoff does not contain the requested publication"
            )
        if any(
            entry.commit != revision.commit
            or entry.tree != revision.tree
            or entry.repository_binding_id != revision.repository_binding_id
            or entry.repository_binding_version
            != revision.repository_binding_version
            or entry.repository_id != revision.repository_id
            for entry in selected
        ):
            raise NativeRevisionPathFetchError(
                "handoff entries differ from the exact published revision"
            )
        reference_service = RevisionPathReferenceService(self.repositories)
        for entry in selected:
            reference_service.require_exact(
                entry,
                project_id=revision.project_id,
                session_id=session_id,
            )
        binding = self.repositories.project_repository_bindings.get(
            revision.repository_binding_id
        )
        if (
            binding is None
            or binding.binding_version != revision.repository_binding_version
            or binding.repository_id != revision.repository_id
        ):
            raise NativeRevisionPathFetchError(
                "published revision repository binding is unavailable or drifted"
            )

        git_arguments: list[str] = [
            revision.publication_ref,
            revision.publication_id,
            revision.commit,
            revision.tree,
        ]
        for entry in selected:
            git_arguments.extend(
                (
                    entry.ref_id,
                    entry.path,
                    entry.entry_kind.value,
                    entry.object_id,
                    "" if entry.size_bytes is None else str(entry.size_bytes),
                )
            )
        git_result = self.runtime.execute(
            session_id=session_id,
            agent_id=agent_id,
            argv=(
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                _GIT_VERIFY_SCRIPT,
                "openzyme-publication-fetch",
                *git_arguments,
            ),
            credential_request=AgentProcessCredentialRequest(
                service_id=binding.internal_git_service_id,
                target_id=binding.repository_id,
                protocol="git_read",
                audience=binding.internal_git_endpoint,
            ),
        )
        git_verified = _verified_ids(git_result, marker="OPENZYME_GIT_REF=")
        expected_git_ids = tuple(entry.ref_id for entry in selected)
        if git_result["returncode"] != 0 or git_verified != expected_git_ids:
            raise NativeRevisionPathFetchError(
                "native Git fetch did not verify every exact handoff entry"
            )

        lfs_entries = tuple(
            entry
            for entry in selected
            if entry.entry_kind is RevisionPathEntryKind.LFS_FILE
        )
        lfs_digest = None
        if lfs_entries:
            lfs_arguments: list[str] = [revision.publication_ref]
            for entry in lfs_entries:
                assert entry.lfs_oid is not None
                assert entry.lfs_size_bytes is not None
                lfs_arguments.extend(
                    (
                        entry.ref_id,
                        entry.commit,
                        entry.path,
                        entry.object_id,
                        entry.lfs_oid,
                        str(entry.lfs_size_bytes),
                    )
                )
            lfs_result = self.runtime.execute(
                session_id=session_id,
                agent_id=agent_id,
                argv=(
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    _LFS_VERIFY_SCRIPT,
                    "openzyme-lfs-fetch",
                    *lfs_arguments,
                ),
                credential_request=AgentProcessCredentialRequest(
                    service_id=binding.lfs_service_id,
                    target_id=binding.repository_id,
                    protocol="lfs_read",
                    audience=binding.lfs_endpoint,
                ),
            )
            lfs_verified = _verified_ids(lfs_result, marker="OPENZYME_LFS_REF=")
            if (
                lfs_result["returncode"] != 0
                or lfs_verified != tuple(entry.ref_id for entry in lfs_entries)
            ):
                raise NativeRevisionPathFetchError(
                    "native Git LFS fetch did not verify every exact LFS object"
                )
            lfs_digest = str(lfs_result["result_digest"])

        return NativeRevisionPathFetchResult(
            handoff_id=handoff.handoff_id,
            publication_id=revision.publication_id,
            commit=revision.commit,
            tree=revision.tree,
            verified_ref_ids=expected_git_ids,
            git_process_digest=str(git_result["result_digest"]),
            lfs_process_digest=lfs_digest,
        )


def _verified_ids(
    result: dict[str, object],
    *,
    marker: str,
) -> tuple[str, ...]:
    return tuple(
        line.removeprefix(marker)
        for line in str(result.get("stdout") or "").splitlines()
        if line.startswith(marker)
    )


__all__ = [
    "NativeRevisionPathFetchError",
    "NativeRevisionPathFetchResult",
    "NativeRevisionPathFetchService",
]
