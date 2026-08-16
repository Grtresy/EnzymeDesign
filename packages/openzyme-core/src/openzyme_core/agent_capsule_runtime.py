from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
import json
import re
from typing import Protocol
from uuid import uuid4

from openzyme_domain import GENERAL_AGENT_CAPABILITIES
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentWorkspaceStateObservation
from openzyme_domain import ExecutorHpcCredentialOperation
from openzyme_domain import ExecutorHpcWorkspaceState
from openzyme_domain import PrivateRefAdvanceKind
from openzyme_domain import RemotePrivateRefObservation
from openzyme_domain import RepositoryRefClass
from openzyme_domain import WorkspaceCheckpointProofInput
from openzyme_domain import WorkspaceDirtyState
from openzyme_domain import WorkspaceFormalBoundary

from .agent_capability_service import ActiveAgentCapabilityLeaseClaims
from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .agent_capability_service import AgentCapabilityAdmissionRequest
from .agent_capability_service import AgentCapabilityError
from .agent_capsule_image import CapsuleCommandExecutor
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import CoreRepositories
from .executor_hpc_workspaces import ExecutorHpcWorkspaceService
from .repository_credentials import IssuedRepositoryCredential
from .repository_credentials import RepositoryCredentialBroker
from .repository_credentials import RepositoryCredentialProtocol
from .workspace_checkpoints import WorkspaceCheckpointError
from .workspace_checkpoints import WorkspaceCheckpointService


AGENT_CAPSULE_PROCESS_RESULT_SCHEMA_VERSION = "agent_capsule_process_result@1"
AGENT_PROCESS_CREDENTIAL_REQUEST_SCHEMA_VERSION = (
    "agent_process_credential_request@1"
)
NATIVE_PROCESS_DEFAULT_TIMEOUT_SECONDS = 120
NATIVE_PROCESS_MAX_TIMEOUT_SECONDS = 3_600
NATIVE_PROCESS_OUTPUT_LIMIT_BYTES = 256 * 1024
_SAFE_NETWORK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_WORKSPACE_STATUS_SCRIPT = r"""
set -eu
head_commit=$(git rev-parse --verify HEAD)
head_tree=$(git rev-parse --verify 'HEAD^{tree}')
printf 'OPENZYME_HEAD=%s\nOPENZYME_TREE=%s\n' "$head_commit" "$head_tree"
git status --porcelain=v1 --untracked-files=normal | awk '
BEGIN { staged=0; unstaged=0; untracked=0 }
substr($0,1,2)=="??" { untracked=1; next }
substr($0,1,1)!=" " { staged=1 }
substr($0,2,1)!=" " { unstaged=1 }
END {
  printf "OPENZYME_STAGED=%d\n", staged
  printf "OPENZYME_UNSTAGED=%d\n", unstaged
  printf "OPENZYME_UNTRACKED=%d\n", untracked
}
'
""".strip()


class AgentCapsuleRuntimeError(RuntimeError):
    error_code = "agent_capsule_runtime_error"


class AgentCapsuleAdmissionError(AgentCapsuleRuntimeError):
    error_code = "agent_capsule_admission_rejected"


class AgentCapsuleCredentialError(AgentCapsuleRuntimeError):
    error_code = "agent_capsule_credential_rejected"


@dataclass(frozen=True, slots=True)
class AgentProcessCredentialRequest:
    service_id: str
    target_id: str
    protocol: str
    audience: str
    schema_version: str = AGENT_PROCESS_CREDENTIAL_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_PROCESS_CREDENTIAL_REQUEST_SCHEMA_VERSION:
            raise ValueError("unsupported process credential request schema")
        for field_name in ("service_id", "target_id", "protocol", "audience"):
            value = getattr(self, field_name)
            if not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{field_name} must not be empty, padded, or contain NUL")


@dataclass(frozen=True, slots=True)
class IssuedAgentProcessCredential:
    credential_id: str
    service_id: str
    target_id: str
    protocol: str
    audience: str
    environment: tuple[tuple[str, str], ...]
    exact_secret_material: tuple[str, ...]
    expires_at: str

    def __post_init__(self) -> None:
        keys = tuple(key for key, _ in self.environment)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("credential environment names must be unique and sorted")
        if not self.exact_secret_material or any(
            not value for value in self.exact_secret_material
        ):
            raise ValueError("credential must carry exact non-empty secret material")


class AgentProcessCredentialProvider(Protocol):
    service_id: str

    def issue(
        self,
        *,
        request: AgentProcessCredentialRequest,
        claims: ActiveAgentCapabilityLeaseClaims,
        now: datetime,
    ) -> IssuedAgentProcessCredential: ...

    def revoke(
        self,
        credential: IssuedAgentProcessCredential,
        *,
        revoked_at: str,
    ) -> None: ...


@dataclass(slots=True)
class AgentProcessCredentialRouter:
    providers: dict[str, AgentProcessCredentialProvider]

    def issue(
        self,
        *,
        request: AgentProcessCredentialRequest,
        claims: ActiveAgentCapabilityLeaseClaims,
        now: datetime,
    ) -> tuple[AgentProcessCredentialProvider, IssuedAgentProcessCredential]:
        provider = self.providers.get(request.service_id)
        if provider is None or provider.service_id != request.service_id:
            raise AgentCapsuleCredentialError(
                f"no process credential provider for service {request.service_id!r}"
            )
        credential = provider.issue(request=request, claims=claims, now=now)
        if (
            credential.service_id != request.service_id
            or credential.target_id != request.target_id
            or credential.protocol != request.protocol
            or credential.audience != request.audience
        ):
            provider.revoke(
                credential,
                revoked_at=now.isoformat(),
            )
            raise AgentCapsuleCredentialError(
                "process credential provider changed the exact requested audience"
            )
        return provider, credential


@dataclass(slots=True)
class RepositoryAgentProcessCredentialProvider:
    repositories: CoreRepositories
    broker: RepositoryCredentialBroker
    service_id: str

    def issue(
        self,
        *,
        request: AgentProcessCredentialRequest,
        claims: ActiveAgentCapabilityLeaseClaims,
        now: datetime,
    ) -> IssuedAgentProcessCredential:
        workspace = claims.require_workspace()
        binding = self.repositories.project_repository_bindings.get(
            workspace.repository_binding_id
        )
        pin = self.repositories.session_repository_binding_pins.require(
            workspace.session_id
        )
        if binding is None:
            raise AgentCapsuleCredentialError("workspace repository binding is missing")
        protocols = {
            item.value: item
            for item in (
                RepositoryCredentialProtocol.GIT_READ,
                RepositoryCredentialProtocol.GIT_WRITE,
                RepositoryCredentialProtocol.LFS_READ,
                RepositoryCredentialProtocol.LFS_WRITE,
            )
        }
        protocol = protocols.get(request.protocol)
        if protocol is None:
            raise AgentCapsuleCredentialError(
                "repository process credential protocol is unsupported"
            )
        expected_service_id = (
            binding.lfs_service_id
            if protocol
            in {
                RepositoryCredentialProtocol.LFS_READ,
                RepositoryCredentialProtocol.LFS_WRITE,
            }
            else binding.internal_git_service_id
        )
        expected_audience = (
            binding.lfs_endpoint
            if protocol
            in {
                RepositoryCredentialProtocol.LFS_READ,
                RepositoryCredentialProtocol.LFS_WRITE,
            }
            else binding.internal_git_endpoint
        )
        if (
            request.service_id != expected_service_id
            or request.target_id != binding.repository_id
            or request.audience != expected_audience
        ):
            raise AgentCapsuleCredentialError(
                "repository process credential audience does not match session pin"
            )
        write = protocol in {
            RepositoryCredentialProtocol.GIT_WRITE,
            RepositoryCredentialProtocol.LFS_WRITE,
        }
        issued = self.broker.issue(
            binding=binding,
            pin=pin,
            capability_lease_id=claims.lease.lease_id,
            expected_agent_member_id=workspace.agent_member_id,
            expected_agent_id=workspace.agent_id,
            expected_workspace_generation=workspace.workspace_generation,
            protocols=(protocol,),
            ref_classes=(
                (RepositoryRefClass.READ, RepositoryRefClass.PRIVATE)
                if write
                else (RepositoryRefClass.READ,)
            ),
            now=now,
        )
        return _repository_process_credential(
            issued,
            request=request,
        )

    def revoke(
        self,
        credential: IssuedAgentProcessCredential,
        *,
        revoked_at: str,
    ) -> None:
        self.broker.revoke(credential.credential_id, revoked_at=revoked_at)


@dataclass(slots=True)
class ExecutorHpcAgentProcessCredentialProvider:
    service: ExecutorHpcWorkspaceService
    service_id: str
    target_profile_id: str

    def issue(
        self,
        *,
        request: AgentProcessCredentialRequest,
        claims: ActiveAgentCapabilityLeaseClaims,
        now: datetime,
    ) -> IssuedAgentProcessCredential:
        if (
            request.service_id != self.service_id
            or request.target_id != self.target_profile_id
            or request.protocol
            not in {item.value for item in ExecutorHpcCredentialOperation}
        ):
            raise AgentCapsuleCredentialError(
                "native HPC credential request is outside the target qualification"
            )
        candidates = [
            workspace
            for workspace in self.service.repositories.executor_hpc_workspaces.list_by_agent_member(
                session_id=claims.require_workspace().session_id,
                agent_member_id=claims.require_workspace().agent_member_id,
            )
            if workspace.target_profile_id == self.target_profile_id
            and workspace.state is ExecutorHpcWorkspaceState.READY
            and workspace.local_workspace_generation
            == claims.require_workspace().workspace_generation
            and workspace.capability_lease_id == claims.lease.lease_id
            and workspace.capability_lease_version == claims.lease.state_version
        ]
        if len(candidates) != 1:
            raise AgentCapsuleCredentialError(
                "native HPC credential requires one exact ready workspace generation"
            )
        workspace = candidates[0]
        if request.audience != workspace.workspace_id:
            raise AgentCapsuleCredentialError(
                "native HPC credential audience must be the opaque workspace id"
            )
        issued = self.service.issue_native_credential(
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_id=workspace.executor_agent_id,
            claim_id=f"hpc_credential_{uuid4().hex}",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
            operations=(ExecutorHpcCredentialOperation(request.protocol),),
        )
        return IssuedAgentProcessCredential(
            credential_id=issued.claim.claim_id,
            service_id=self.service_id,
            target_id=self.target_profile_id,
            protocol=request.protocol,
            audience=workspace.workspace_id,
            environment=issued.environment,
            exact_secret_material=issued.exact_secret_material,
            expires_at=issued.claim.expires_at,
        )

    def revoke(
        self,
        credential: IssuedAgentProcessCredential,
        *,
        revoked_at: str,
    ) -> None:
        self.service.revoke_native_credential(
            claim_id=credential.credential_id,
            revoked_at=revoked_at,
        )


@dataclass(frozen=True, slots=True)
class AgentCapsuleProcessResult:
    returncode: int
    stdout: str
    stderr: str


class AgentCapsuleProcessRunner(Protocol):
    def run(
        self,
        *,
        workspace: AgentGitWorkspace,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> AgentCapsuleProcessResult: ...


@dataclass(slots=True)
class PodmanAgentCapsuleProcessRunner:
    executor: CapsuleCommandExecutor
    deployment_network: str
    podman_binary: str = "/usr/bin/podman"

    def __post_init__(self) -> None:
        if _SAFE_NETWORK_NAME.fullmatch(self.deployment_network) is None:
            raise ValueError("deployment_network is not a safe Podman network name")

    def run(
        self,
        *,
        workspace: AgentGitWorkspace,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> AgentCapsuleProcessResult:
        environment = {"PATH": "/usr/bin:/bin", **dict(credential_environment)}
        command: list[str] = [
            self.podman_binary,
            "run",
            "--rm",
            "--network",
            self.deployment_network,
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,uid=10001,gid=10001,mode=0700",
            "--volume",
            f"{workspace.volume_id}:/workspace:rw",
            "--workdir",
            workspace.clone_logical_root,
        ]
        for key, _ in credential_environment:
            command.extend(("--env", key))
        command.extend(
            (
                workspace.image_ref,
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=5",
                str(timeout_seconds),
                *argv,
            )
        )
        result = self.executor.run(tuple(command), environment=environment)
        return AgentCapsuleProcessResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


@dataclass(slots=True)
class AgentCapsuleRuntimeService:
    repositories: CoreRepositories
    process_runner: AgentCapsuleProcessRunner
    credential_router: AgentProcessCredentialRouter | None = None

    def execute(
        self,
        *,
        session_id: str,
        agent_id: str,
        argv: tuple[str, ...],
        timeout_seconds: int = NATIVE_PROCESS_DEFAULT_TIMEOUT_SECONDS,
        credential_request: AgentProcessCredentialRequest | None = None,
    ) -> dict[str, object]:
        _validate_native_argv(argv)
        if timeout_seconds <= 0 or timeout_seconds > NATIVE_PROCESS_MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be between 1 and {NATIVE_PROCESS_MAX_TIMEOUT_SECONDS}"
            )
        agent = self.repositories.agents.get(session_id, agent_id)
        if agent is None or agent.member_id is None:
            raise AgentCapsuleAdmissionError("canonical agent member does not exist")
        workspace = self.repositories.agent_git_workspaces.get_current(
            session_id=session_id,
            agent_member_id=agent.member_id,
        )
        if workspace is None or workspace.status is not AgentGitWorkspaceStatus.READY:
            raise AgentCapsuleAdmissionError(
                "native capsule requires the exact ready agent Git workspace"
            )
        claims = ActiveAgentCapabilityLeaseValidator(self.repositories).validate(
            AgentCapabilityAdmissionRequest(
                lease_id=workspace.capability_lease_id,
                session_id=session_id,
                agent_member_id=agent.member_id,
                agent_id=agent_id,
                workspace_generation=workspace.workspace_generation,
                service_id="agent_native_capsule",
                target_id="network:deployment",
                protocol="native_process",
                operation_class="workspace_exec",
                required_capabilities=GENERAL_AGENT_CAPABILITIES,
            )
        )
        provider: AgentProcessCredentialProvider | None = None
        credential: IssuedAgentProcessCredential | None = None
        if credential_request is not None:
            if self.credential_router is None:
                raise AgentCapsuleCredentialError(
                    "Host process credential router is unavailable"
                )
            provider, credential = self.credential_router.issue(
                request=credential_request,
                claims=claims,
                now=datetime.now(tz=UTC),
            )
        credential_environment = () if credential is None else credential.environment
        secret_material = () if credential is None else credential.exact_secret_material
        try:
            try:
                result = self.process_runner.run(
                    workspace=workspace,
                    argv=argv,
                    credential_environment=credential_environment,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                diagnostic = _redact_exact_secrets(str(exc), secret_material)
                raise AgentCapsuleRuntimeError(
                    f"native capsule process launch failed: {diagnostic}"
                ) from exc
        finally:
            if provider is not None and credential is not None:
                provider.revoke(
                    credential,
                    revoked_at=datetime.now(tz=UTC).isoformat(),
                )
        stdout = _redact_exact_secrets(result.stdout, secret_material)
        stderr = _redact_exact_secrets(result.stderr, secret_material)
        stdout, stdout_truncated = _bounded_output(stdout)
        stderr, stderr_truncated = _bounded_output(stderr)
        payload = {
            "schema_version": AGENT_CAPSULE_PROCESS_RESULT_SCHEMA_VERSION,
            "workspace_id": workspace.workspace_id,
            "workspace_generation": workspace.workspace_generation,
            "cwd": workspace.clone_logical_root,
            "head_commit_before": workspace.head_commit,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "retry_performed": False,
            "fallback_performed": False,
            "credential_issued": credential is not None,
        }
        payload["result_digest"] = _json_digest(payload)
        return payload


def agent_capsule_tools_available(
    repositories: CoreRepositories,
    *,
    session_id: str,
    agent_id: str,
) -> bool:
    agent = repositories.agents.get(session_id, agent_id)
    if agent is None or agent.member_id is None:
        return False
    workspace = repositories.agent_git_workspaces.get_current(
        session_id=session_id,
        agent_member_id=agent.member_id,
    )
    if workspace is None or workspace.status is not AgentGitWorkspaceStatus.READY:
        return False
    try:
        ActiveAgentCapabilityLeaseValidator(repositories).validate(
            AgentCapabilityAdmissionRequest(
                lease_id=workspace.capability_lease_id,
                session_id=session_id,
                agent_member_id=agent.member_id,
                agent_id=agent_id,
                workspace_generation=workspace.workspace_generation,
                service_id="agent_native_capsule",
                target_id="network:deployment",
                protocol="tool_exposure",
                operation_class="workspace_exec_exposure",
                required_capabilities=GENERAL_AGENT_CAPABILITIES,
            )
        )
    except AgentCapabilityError:
        return False
    return True


def register_agent_capsule_tools(
    registry: ToolRegistry,
    *,
    agent_id: str | None,
) -> None:
    def handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        resolved_agent_id = agent_id or context.agent_id
        if not resolved_agent_id:
            return _tool_error(
                invocation,
                "agent_capsule_admission_rejected",
                "workspace.exec requires a canonical agent identity",
            )
        runner = getattr(context, "agent_capsule_process_runner", None)
        if runner is None:
            return _tool_error(
                invocation,
                "agent_capsule_runtime_unavailable",
                "native agent capsule process runner is not configured",
            )
        raw_argv = invocation.arguments.get("argv")
        if not isinstance(raw_argv, list) or not all(
            isinstance(item, str) for item in raw_argv
        ):
            return _tool_error(
                invocation,
                "invalid_tool_arguments",
                "workspace.exec argv must be an array of strings",
            )
        raw_credential = invocation.arguments.get("credential")
        credential_request = None
        if raw_credential is not None:
            if not isinstance(raw_credential, dict):
                return _tool_error(
                    invocation,
                    "invalid_tool_arguments",
                    "workspace.exec credential must be an object",
                )
            try:
                credential_request = AgentProcessCredentialRequest(
                    service_id=str(raw_credential["service_id"]),
                    target_id=str(raw_credential["target_id"]),
                    protocol=str(raw_credential["protocol"]),
                    audience=str(raw_credential["audience"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                return _tool_error(
                    invocation,
                    "invalid_tool_arguments",
                    str(exc),
                )
        service = AgentCapsuleRuntimeService(
            repositories=context.repositories,
            process_runner=runner,
            credential_router=getattr(
                context,
                "agent_process_credential_router",
                None,
            ),
        )
        try:
            payload = service.execute(
                session_id=context.snapshot.session.session_id,
                agent_id=resolved_agent_id,
                argv=tuple(raw_argv),
                timeout_seconds=int(
                    invocation.arguments.get("timeout_seconds")
                    or NATIVE_PROCESS_DEFAULT_TIMEOUT_SECONDS
                ),
                credential_request=credential_request,
            )
        except (AgentCapabilityError, AgentCapsuleRuntimeError, ValueError) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "agent_capsule_runtime_error"),
                str(exc),
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=payload["returncode"] == 0,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status=(
                "agent_capsule_process_completed"
                if payload["returncode"] == 0
                else "agent_capsule_process_failed"
            ),
            summary=(
                "Native workspace process completed."
                if payload["returncode"] == 0
                else f"Native workspace process exited {payload['returncode']}."
            ),
            error_code=(
                None
                if payload["returncode"] == 0
                else "native_process_nonzero_exit"
            ),
            details={
                "workspace_id": payload["workspace_id"],
                "workspace_generation": payload["workspace_generation"],
                "returncode": payload["returncode"],
                "retry_performed": False,
                "fallback_performed": False,
            },
        )

    def status_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        resolved_agent_id = agent_id or context.agent_id
        runner = context.agent_capsule_process_runner
        git_reader = context.workspace_checkpoint_git_reader
        if not resolved_agent_id or runner is None or git_reader is None:
            return _tool_error(
                invocation,
                "workspace_checkpoint_unavailable",
                "workspace status requires exact agent, capsule, and repository services",
            )
        runtime = AgentCapsuleRuntimeService(
            repositories=context.repositories,
            process_runner=runner,
        )
        try:
            result = runtime.execute(
                session_id=context.snapshot.session.session_id,
                agent_id=resolved_agent_id,
                argv=("/bin/sh", "-c", _WORKSPACE_STATUS_SCRIPT),
            )
            if result["returncode"] != 0:
                return ToolResult(
                    call_id=invocation.call_id,
                    tool_name=invocation.tool_name,
                    ok=False,
                    content=json.dumps(result, sort_keys=True),
                    status="workspace_status_failed",
                    summary="Native Git workspace observation failed.",
                    error_code="native_process_nonzero_exit",
                    details={
                        "returncode": result["returncode"],
                        "retry_performed": False,
                        "fallback_performed": False,
                    },
                )
            facts = _parse_workspace_status_output(str(result["stdout"]))
            workspace = context.repositories.agent_git_workspaces.get(
                str(result["workspace_id"])
            )
            if workspace is None:
                raise WorkspaceCheckpointError("observed workspace disappeared")
            staged = facts["OPENZYME_STAGED"] == "1"
            unstaged = facts["OPENZYME_UNSTAGED"] == "1"
            untracked = facts["OPENZYME_UNTRACKED"] == "1"
            observation = AgentWorkspaceStateObservation(
                observation_id=f"workspace_observation_{uuid4().hex}",
                workspace_id=workspace.workspace_id,
                session_id=workspace.session_id,
                agent_member_id=workspace.agent_member_id,
                agent_id=workspace.agent_id,
                workspace_generation=workspace.workspace_generation,
                head_commit=facts["OPENZYME_HEAD"],
                head_tree=facts["OPENZYME_TREE"],
                dirty_state=(
                    WorkspaceDirtyState.DIRTY
                    if staged or unstaged or untracked
                    else WorkspaceDirtyState.CLEAN
                ),
                staged=staged,
                unstaged=unstaged,
                untracked=untracked,
                observed_at=datetime.now(tz=UTC).isoformat(),
            )
            stored = WorkspaceCheckpointService(
                context.repositories,
                git_reader,
            ).record_state_observation(observation)
        except (
            AgentCapabilityError,
            AgentCapsuleRuntimeError,
            WorkspaceCheckpointError,
            ValueError,
        ) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "workspace_status_rejected"),
                str(exc),
            )
        payload = {
            "observation_id": stored.observation_id,
            "workspace_id": stored.workspace_id,
            "workspace_generation": stored.workspace_generation,
            "head_commit": stored.head_commit,
            "head_tree": stored.head_tree,
            "dirty_state": stored.dirty_state.value,
            "staged": stored.staged,
            "unstaged": stored.unstaged,
            "untracked": stored.untracked,
            "observed_at": stored.observed_at,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            status="workspace_status_observed",
            summary="Observed exact private workspace Git state without mutation.",
            details=payload,
        )

    def checkpoint_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        resolved_agent_id = agent_id or context.agent_id
        git_reader = context.workspace_checkpoint_git_reader
        if not resolved_agent_id or git_reader is None:
            return _tool_error(
                invocation,
                "workspace_checkpoint_unavailable",
                "checkpoint verification requires exact agent and repository services",
            )
        agent = context.repositories.agents.get(
            context.snapshot.session.session_id,
            resolved_agent_id,
        )
        workspace = (
            None
            if agent is None or agent.member_id is None
            else context.repositories.agent_git_workspaces.get_current(
                session_id=context.snapshot.session.session_id,
                agent_member_id=agent.member_id,
            )
        )
        if workspace is None:
            return _tool_error(
                invocation,
                "workspace_checkpoint_rejected",
                "checkpoint verification requires an exact current workspace",
            )
        raw_observation = invocation.arguments.get("remote_observation")
        if not isinstance(raw_observation, dict):
            return _tool_error(
                invocation,
                "invalid_tool_arguments",
                "remote_observation must be an object",
            )
        try:
            private_ref = str(invocation.arguments["private_ref"])
            commit = str(invocation.arguments["commit"])
            remote_observation = RemotePrivateRefObservation(
                service_id=str(raw_observation["service_id"]),
                repository_id=str(raw_observation["repository_id"]),
                private_ref=private_ref,
                prior_commit=(
                    None
                    if raw_observation.get("prior_commit") is None
                    else str(raw_observation["prior_commit"])
                ),
                observed_commit=commit,
                advance_kind=PrivateRefAdvanceKind(
                    str(raw_observation["advance_kind"])
                ),
                observed_at=str(raw_observation["observed_at"]),
            )
            proof = WorkspaceCheckpointProofInput(
                boundary=WorkspaceFormalBoundary(
                    str(invocation.arguments["boundary"])
                ),
                workspace_id=workspace.workspace_id,
                session_id=workspace.session_id,
                agent_member_id=workspace.agent_member_id,
                agent_id=workspace.agent_id,
                workspace_generation=int(
                    invocation.arguments["workspace_generation"]
                ),
                repository_binding_id=workspace.repository_binding_id,
                repository_binding_version=workspace.repository_binding_version,
                commit=commit,
                tree=str(invocation.arguments["tree"]),
                private_ref=private_ref,
                remote_observation=remote_observation,
            )
            checkpoint = WorkspaceCheckpointService(
                context.repositories,
                git_reader,
            ).verify_checkpoint(proof)
        except (
            KeyError,
            TypeError,
            ValueError,
            AgentCapabilityError,
            WorkspaceCheckpointError,
        ) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "workspace_checkpoint_rejected"),
                str(exc),
            )
        payload = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "boundary": checkpoint.boundary.value,
            "workspace_id": checkpoint.workspace_id,
            "workspace_generation": checkpoint.workspace_generation,
            "commit": checkpoint.commit,
            "tree": checkpoint.tree,
            "private_ref": checkpoint.private_ref,
            "advance_kind": checkpoint.advance_kind.value,
            "verified_at": checkpoint.verified_at,
            "truth_scope": "owner_private_not_team_shared",
            "published_revision_created": False,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            status="workspace_checkpoint_verified",
            summary="Verified an owner-private append-only Git checkpoint.",
            details=payload,
        )

    registry.register("workspace.exec", handler)
    registry.register("workspace.status", status_handler)
    registry.register("workspace.checkpoint.verify", checkpoint_handler)


def _repository_process_credential(
    issued: IssuedRepositoryCredential,
    *,
    request: AgentProcessCredentialRequest,
) -> IssuedAgentProcessCredential:
    authorization = f"Authorization: Bearer {issued.token}"
    audience_scoped_header = f"http.{request.audience}.extraHeader"
    return IssuedAgentProcessCredential(
        credential_id=issued.claims.credential_id,
        service_id=request.service_id,
        target_id=request.target_id,
        protocol=request.protocol,
        audience=request.audience,
        environment=tuple(
            sorted(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": audience_scoped_header,
                    "GIT_CONFIG_VALUE_0": authorization,
                }.items()
            )
        ),
        exact_secret_material=(issued.token, authorization),
        expires_at=issued.claims.expires_at,
    )


def _parse_workspace_status_output(value: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, item = line.partition("=")
        if separator and key.startswith("OPENZYME_"):
            facts[key] = item
    required = {
        "OPENZYME_HEAD",
        "OPENZYME_TREE",
        "OPENZYME_STAGED",
        "OPENZYME_UNSTAGED",
        "OPENZYME_UNTRACKED",
    }
    if set(facts) != required:
        raise WorkspaceCheckpointError("native Git status output is incomplete")
    dirty_flag_keys = {
        "OPENZYME_STAGED",
        "OPENZYME_UNSTAGED",
        "OPENZYME_UNTRACKED",
    }
    if any(facts[key] not in {"0", "1"} for key in dirty_flag_keys):
        raise WorkspaceCheckpointError("native Git dirty flags are invalid")
    return facts


def _validate_native_argv(argv: tuple[str, ...]) -> None:
    if not argv or len(argv) > 256:
        raise ValueError("argv must contain 1 to 256 arguments")
    total_bytes = 0
    for argument in argv:
        if not isinstance(argument, str) or not argument or "\x00" in argument:
            raise ValueError("argv entries must be non-empty strings without NUL")
        total_bytes += len(argument.encode("utf-8"))
    if total_bytes > 128 * 1024:
        raise ValueError("argv exceeds the native process byte limit")


def _redact_exact_secrets(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED_PROCESS_CREDENTIAL]")
    return redacted


def _bounded_output(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= NATIVE_PROCESS_OUTPUT_LIMIT_BYTES:
        return value, False
    bounded = encoded[:NATIVE_PROCESS_OUTPUT_LIMIT_BYTES]
    return bounded.decode("utf-8", errors="replace"), True


def _json_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _tool_error(
    invocation: ToolInvocation,
    error_code: str,
    message: str,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=message,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=error_code,
        summary=message,
        error_code=error_code,
        hint="Inspect canonical workspace and capability state; do not retry implicitly.",
        details={"retry_performed": False, "fallback_performed": False},
    )


__all__ = [
    "AGENT_CAPSULE_PROCESS_RESULT_SCHEMA_VERSION",
    "AGENT_PROCESS_CREDENTIAL_REQUEST_SCHEMA_VERSION",
    "AgentCapsuleAdmissionError",
    "AgentCapsuleCredentialError",
    "AgentCapsuleProcessResult",
    "AgentCapsuleProcessRunner",
    "AgentCapsuleRuntimeError",
    "AgentCapsuleRuntimeService",
    "AgentProcessCredentialProvider",
    "AgentProcessCredentialRequest",
    "AgentProcessCredentialRouter",
    "ExecutorHpcAgentProcessCredentialProvider",
    "IssuedAgentProcessCredential",
    "NATIVE_PROCESS_DEFAULT_TIMEOUT_SECONDS",
    "NATIVE_PROCESS_MAX_TIMEOUT_SECONDS",
    "PodmanAgentCapsuleProcessRunner",
    "RepositoryAgentProcessCredentialProvider",
    "agent_capsule_tools_available",
    "register_agent_capsule_tools",
]
