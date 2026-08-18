from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import require_repository_path

from .harness import SessionRuntimeContext


# Each chunk is transported as one bounded base64 argv into the capsule. Larger
# content uses multiple native capsule turns and becomes visible only after the
# final whole-file digest check and atomic rename.
WORKSPACE_FILE_WRITE_MAX_BYTES = 16 * 1024 * 1024
_WORKSPACE_FILE_WRITE_CHUNK_BYTES = 80 * 1024
_WORKSPACE_FILE_WRITE_CHUNKS_PER_PROCESS = 8
_SAFE_FILE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


@dataclass(frozen=True, slots=True)
class WorkspaceFileCleanupResult:
    temporary_path: str
    attempted: bool
    completed: bool
    returncode: int | None
    failure_kind: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None
    stdout: str | None = None
    stderr: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "workspace_file_cleanup_result@1",
            "temporary_path": self.temporary_path,
            "attempted": self.attempted,
            "completed": self.completed,
            "returncode": self.returncode,
            "failure_kind": self.failure_kind,
            "exception_type": self.exception_type,
        }

    def to_private_dict(self) -> dict[str, object]:
        return {
            **self.to_dict(),
            "exception_message": self.exception_message,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class WorkspaceFileHandoffError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        phase: str = "preflight",
        temporary_path: str | None = None,
        mutation_applied: bool = False,
        cleanup_result: WorkspaceFileCleanupResult | None = None,
        primary_failure: BaseException | None = None,
        returncode: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        self.error_code = (
            "workspace_file_cleanup_incomplete"
            if cleanup_result is not None and not cleanup_result.completed
            else "workspace_file_handoff_failed"
        )
        self.phase = phase
        self.temporary_path = temporary_path
        self.mutation_applied = mutation_applied
        self.fallback_performed = False
        self.cleanup_result = cleanup_result
        self.primary_failure = primary_failure
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        ordered_failures: list[dict[str, object]] = []
        if primary_failure is not None:
            ordered_failures.append(
                {
                    "order": 1,
                    "role": "primary",
                    "type": primary_failure.__class__.__qualname__,
                    "message": str(primary_failure),
                    "error_code": getattr(primary_failure, "error_code", None),
                }
            )
        if cleanup_result is not None and not cleanup_result.completed:
            ordered_failures.append(
                {
                    "order": len(ordered_failures) + 1,
                    "role": "cleanup",
                    "type": cleanup_result.exception_type,
                    "failure_kind": cleanup_result.failure_kind,
                    "returncode": cleanup_result.returncode,
                }
            )
        self.diagnostic_context = {
            "phase": phase,
            "temporary_path": temporary_path,
            "mutation_applied": mutation_applied,
            "fallback_performed": False,
            "cleanup": (
                None if cleanup_result is None else cleanup_result.to_private_dict()
            ),
            "ordered_failures": ordered_failures,
        }
        detail = (
            f" phase={phase} temporary_path={temporary_path} "
            f"mutation_applied={str(mutation_applied).lower()} "
            f"cleanup_completed="
            f"{None if cleanup_result is None else cleanup_result.completed}"
        )
        super().__init__(message + detail)

    def to_public_details(self) -> dict[str, object]:
        cleanup_incomplete = (
            self.cleanup_result is not None and not self.cleanup_result.completed
        )
        return {
            "component": "openzyme_core.workspace_file_handoffs",
            "operation": self.phase,
            "phase": self.phase,
            "effect_certainty": (
                "terminal_known" if self.mutation_applied else "no_effect"
            ),
            "retry_eligibility": (
                "reconcile_required" if cleanup_incomplete else "same_phase_safe"
            ),
            "next_action": (
                "cleanup_temporary_file"
                if cleanup_incomplete
                else "retry_same_phase"
            ),
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "temporary_repository_path": self.temporary_path,
            "cleanup": (
                None
                if self.cleanup_result is None
                else self.cleanup_result.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class WorkspaceFileWriteResult:
    workspace_id: str
    workspace_generation: int
    repository_path: str
    size_bytes: int
    content_digest: str
    publication_required: bool = True
    commit_performed: bool = False
    publication_performed: bool = False
    cleanup_result: WorkspaceFileCleanupResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "workspace_file_write_result@2",
            "workspace_id": self.workspace_id,
            "workspace_generation": self.workspace_generation,
            "repository_path": self.repository_path,
            "size_bytes": self.size_bytes,
            "content_digest": self.content_digest,
            "publication_required": self.publication_required,
            "commit_performed": self.commit_performed,
            "publication_performed": self.publication_performed,
            "cleanup_result": (
                None if self.cleanup_result is None else self.cleanup_result.to_dict()
            ),
        }


def write_json_to_current_agent_workspace(
    context: SessionRuntimeContext,
    *,
    repository_path: str,
    payload: dict[str, Any],
) -> WorkspaceFileWriteResult:
    content = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return write_bytes_to_current_agent_workspace(
        context,
        repository_path=repository_path,
        content=content,
    )


def write_bytes_to_current_agent_workspace(
    context: SessionRuntimeContext,
    *,
    repository_path: str,
    content: bytes,
) -> WorkspaceFileWriteResult:
    require_repository_path(repository_path)
    if context.agent_id is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result requires a canonical current agent"
        )
    if context.agent_capsule_process_runner is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result requires the native agent capsule writer"
        )
    agent = context.repositories.agents.get(
        context.snapshot.session.session_id,
        context.agent_id,
    )
    if agent is None or agent.member_id is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result agent has no canonical member identity"
        )
    workspace = context.repositories.agent_git_workspaces.get_current(
        session_id=context.snapshot.session.session_id,
        agent_member_id=agent.member_id,
    )
    if workspace is None or workspace.status is not AgentGitWorkspaceStatus.READY:
        raise WorkspaceFileHandoffError(
            "persistent tool result requires the exact ready agent Git workspace"
        )
    if len(content) > WORKSPACE_FILE_WRITE_MAX_BYTES:
        raise WorkspaceFileHandoffError(
            "persistent tool result exceeds the bounded native workspace writer limit"
        )
    digest = hashlib.sha256(content).hexdigest()
    filename = repository_path.rsplit("/", 1)[-1]
    if _SAFE_FILE_COMPONENT.fullmatch(filename) is None:
        raise WorkspaceFileHandoffError(
            "persistent tool result filename is not a safe repository component"
        )
    parent_prefix = (
        repository_path.rsplit("/", 1)[0] + "/"
        if "/" in repository_path
        else ""
    )
    temporary_path = f"{parent_prefix}.openzyme-write-{uuid4().hex}"
    initialize_script = r"""
set -euo pipefail
repository_path="$1"
temporary_path="$2"
case "${repository_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
parent="$(dirname -- "${repository_path}")"
mkdir -p -- "${parent}"
umask 077
( set -o noclobber; : >"${temporary_path}" )
""".strip()
    append_script = r"""
set -euo pipefail
temporary_path="$1"
shift
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
for encoded_chunk in "$@"; do
  printf '%s' "${encoded_chunk}" | base64 -d >>"${temporary_path}"
done
""".strip()
    finalize_script = r"""
set -euo pipefail
repository_path="$1"
temporary_path="$2"
expected_digest="$3"
case "${repository_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
observed_digest="$(sha256sum "${temporary_path}" | cut -d' ' -f1)"
test "${observed_digest}" = "${expected_digest}"
chmod 0600 "${temporary_path}"
mv -- "${temporary_path}" "${repository_path}"
printf 'OPENZYME_PATH=%s\n' "${repository_path}"
printf 'OPENZYME_SHA256=%s\n' "${observed_digest}"
""".strip()
    cleanup_script = r"""
set -euo pipefail
temporary_path="$1"
case "${temporary_path}" in
  /*|*\\*|../*|*/../*|*/..|.git/*|*/.git/*) exit 64 ;;
esac
rm -f -- "${temporary_path}"
test ! -e "${temporary_path}"
printf 'OPENZYME_CLEANUP_PATH=%s\n' "${temporary_path}"
""".strip()

    def cleanup_temporary() -> tuple[WorkspaceFileCleanupResult, BaseException | None]:
        try:
            cleanup_process_result = context.agent_capsule_process_runner.run(
                workspace=workspace,
                argv=(
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    cleanup_script,
                    "openzyme-workspace-file-writer",
                    temporary_path,
                ),
                credential_environment=(),
                timeout_seconds=60,
            )
        except Exception as exc:
            return (
                WorkspaceFileCleanupResult(
                    temporary_path=temporary_path,
                    attempted=True,
                    completed=False,
                    returncode=None,
                    failure_kind="exception",
                    exception_type=exc.__class__.__qualname__,
                    exception_message=str(exc),
                ),
                exc,
            )
        cleanup_confirmed = (
            cleanup_process_result.returncode == 0
            and f"OPENZYME_CLEANUP_PATH={temporary_path}"
            in cleanup_process_result.stdout.splitlines()
        )
        return (
            WorkspaceFileCleanupResult(
                temporary_path=temporary_path,
                attempted=True,
                completed=cleanup_confirmed,
                returncode=cleanup_process_result.returncode,
                failure_kind=None
                if cleanup_confirmed
                else (
                    "nonzero_exit"
                    if cleanup_process_result.returncode != 0
                    else "confirmation_missing"
                ),
                stdout=cleanup_process_result.stdout,
                stderr=cleanup_process_result.stderr,
            ),
            None,
        )

    def raise_write_failure(
        *,
        phase: str,
        message: str,
        primary_failure: BaseException,
        mutation_applied: bool = False,
    ) -> None:
        cleanup_result, cleanup_exception = cleanup_temporary()
        error = WorkspaceFileHandoffError(
            message,
            phase=phase,
            temporary_path=temporary_path,
            mutation_applied=mutation_applied,
            cleanup_result=cleanup_result,
            primary_failure=primary_failure,
            returncode=getattr(primary_failure, "returncode", None),
            stdout=getattr(primary_failure, "stdout", None),
            stderr=getattr(primary_failure, "stderr", None),
        )
        if cleanup_exception is not None:
            error.diagnostic_context["cleanup_exception"] = {
                "type": cleanup_exception.__class__.__qualname__,
                "message": str(cleanup_exception),
            }
        raise error from primary_failure

    def process_failure(
        *,
        phase: str,
        message: str,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> WorkspaceFileHandoffError:
        return WorkspaceFileHandoffError(
            message,
            phase=phase,
            temporary_path=temporary_path,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    try:
        initialize_result = context.agent_capsule_process_runner.run(
            workspace=workspace,
            argv=(
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                initialize_script,
                "openzyme-workspace-file-writer",
                repository_path,
                temporary_path,
            ),
            credential_environment=(),
            timeout_seconds=60,
        )
    except Exception as exc:
        raise_write_failure(
            phase="initialize",
            message="native capsule failed while initializing the workspace file",
            primary_failure=exc,
        )
    if initialize_result.returncode != 0:
        raise_write_failure(
            phase="initialize",
            message="native capsule could not initialize the workspace file write",
            primary_failure=process_failure(
                phase="initialize",
                message="native capsule initialize process returned nonzero",
                returncode=initialize_result.returncode,
                stdout=initialize_result.stdout,
                stderr=initialize_result.stderr,
            ),
        )
    encoded_chunks = tuple(
        base64.b64encode(
            content[offset : offset + _WORKSPACE_FILE_WRITE_CHUNK_BYTES]
        ).decode("ascii")
        for offset in range(0, len(content), _WORKSPACE_FILE_WRITE_CHUNK_BYTES)
    )
    for batch_offset in range(
        0,
        len(encoded_chunks),
        _WORKSPACE_FILE_WRITE_CHUNKS_PER_PROCESS,
    ):
        batch = encoded_chunks[
            batch_offset : batch_offset + _WORKSPACE_FILE_WRITE_CHUNKS_PER_PROCESS
        ]
        try:
            append_result = context.agent_capsule_process_runner.run(
                workspace=workspace,
                argv=(
                    "/bin/bash",
                    "-euo",
                    "pipefail",
                    "-c",
                    append_script,
                    "openzyme-workspace-file-writer",
                    temporary_path,
                    *batch,
                ),
                credential_environment=(),
                timeout_seconds=60,
            )
        except Exception as exc:
            raise_write_failure(
                phase="append",
                message="native capsule failed while appending a workspace file chunk",
                primary_failure=exc,
            )
        if append_result.returncode != 0:
            raise_write_failure(
                phase="append",
                message="native capsule could not append a bounded workspace file chunk",
                primary_failure=process_failure(
                    phase="append",
                    message="native capsule append process returned nonzero",
                    returncode=append_result.returncode,
                    stdout=append_result.stdout,
                    stderr=append_result.stderr,
                ),
            )
    try:
        result = context.agent_capsule_process_runner.run(
            workspace=workspace,
            argv=(
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                finalize_script,
                "openzyme-workspace-file-writer",
                repository_path,
                temporary_path,
                digest,
            ),
            credential_environment=(),
            timeout_seconds=60,
        )
    except Exception as exc:
        raise_write_failure(
            phase="finalize",
            message="native capsule failed while finalizing the workspace file",
            primary_failure=exc,
        )
    if (
        result.returncode != 0
        or f"OPENZYME_PATH={repository_path}" not in result.stdout.splitlines()
        or f"OPENZYME_SHA256={digest}" not in result.stdout.splitlines()
    ):
        raise_write_failure(
            phase="finalize",
            message="native capsule did not confirm the exact workspace file write",
            primary_failure=process_failure(
                phase="finalize",
                message="native capsule finalize result was nonzero or unconfirmed",
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            ),
            mutation_applied=(
                f"OPENZYME_PATH={repository_path}" in result.stdout.splitlines()
                and f"OPENZYME_SHA256={digest}" in result.stdout.splitlines()
            ),
        )
    cleanup_result, cleanup_exception = cleanup_temporary()
    if not cleanup_result.completed:
        primary_failure = WorkspaceFileHandoffError(
            "workspace file write completed but temporary residue cleanup was not proven",
            phase="post_effect_cleanup",
            temporary_path=temporary_path,
            mutation_applied=True,
        )
        error = WorkspaceFileHandoffError(
            "workspace file write completed with cleanup_incomplete",
            phase="post_effect_cleanup",
            temporary_path=temporary_path,
            mutation_applied=True,
            cleanup_result=cleanup_result,
            primary_failure=primary_failure,
        )
        if cleanup_exception is not None:
            error.diagnostic_context["cleanup_exception"] = {
                "type": cleanup_exception.__class__.__qualname__,
                "message": str(cleanup_exception),
            }
        raise error from primary_failure
    return WorkspaceFileWriteResult(
        workspace_id=workspace.workspace_id,
        workspace_generation=workspace.workspace_generation,
        repository_path=repository_path,
        size_bytes=len(content),
        content_digest=f"sha256:{digest}",
        cleanup_result=cleanup_result,
    )


__all__ = [
    "WORKSPACE_FILE_WRITE_MAX_BYTES",
    "WorkspaceFileCleanupResult",
    "WorkspaceFileHandoffError",
    "WorkspaceFileWriteResult",
    "write_bytes_to_current_agent_workspace",
    "write_json_to_current_agent_workspace",
]
