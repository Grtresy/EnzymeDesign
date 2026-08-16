from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
import hashlib
import json
import re
from typing import Protocol
from uuid import uuid4

from openzyme_domain import AgentGitDirectoryKind
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceBlockerCode
from openzyme_domain import AgentGitWorkspaceObservation
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import GitObjectFormat

from .agent_capability_service import AgentCapabilityIssuance
from .agent_capability_service import AgentCapabilityLeaseService
from .agent_capability_service import AgentWorkspaceReadinessProof
from .agent_capsule_image import AgentCapsuleImageQualification
from .agent_capsule_image import CapsuleCommandExecutor
from .agent_capsule_image import load_agent_capsule_image_manifest
from .agent_git_workspace_service import AgentGitWorkspaceLifecycleService
from .agent_workspace_volumes import AgentWorkspaceVolumeAllocator
from .repositories import CoreRepositories
from .repository_provision_credentials import RepositoryProvisionCredentialBroker
from .repository_retention import RepositoryPrivateNamespaceRetentionService


AGENT_GIT_WORKSPACE_READINESS_CANDIDATE_SCHEMA_VERSION = (
    "agent_git_workspace_readiness_candidate@1"
)
_SAFE_NETWORK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class AgentGitWorkspaceProvisioningError(RuntimeError):
    error_code = "agent_git_workspace_provisioning_failed"


@dataclass(frozen=True, slots=True)
class AgentWorkspaceCloneResult:
    returncode: int
    stdout: str
    stderr: str
    head_commit: str | None = None
    head_tree: str | None = None
    object_format: GitObjectFormat | None = None
    remote_endpoint: str | None = None
    independent_git_directory: bool = False


class AgentWorkspaceCloneRunner(Protocol):
    def clone_exact_base(
        self,
        *,
        workspace: AgentGitWorkspace,
        credential_token: str,
    ) -> AgentWorkspaceCloneResult: ...


@dataclass(slots=True)
class PodmanAgentWorkspaceCloneRunner:
    executor: CapsuleCommandExecutor
    deployment_network: str
    podman_binary: str = "/usr/bin/podman"

    def __post_init__(self) -> None:
        if _SAFE_NETWORK_NAME.fullmatch(self.deployment_network) is None:
            raise ValueError("deployment_network is not a safe Podman network name")

    def clone_exact_base(
        self,
        *,
        workspace: AgentGitWorkspace,
        credential_token: str,
    ) -> AgentWorkspaceCloneResult:
        if workspace.status is not AgentGitWorkspaceStatus.PROVISIONING:
            raise AgentGitWorkspaceProvisioningError(
                "clone runner requires an exact provisioning workspace"
            )
        if not credential_token:
            raise AgentGitWorkspaceProvisioningError(
                "clone runner requires a process-scoped provision credential"
            )
        script = r"""
set -euo pipefail
remote_endpoint="$1"
base_commit="$2"
expected_object_format="$3"
clone_root="$4"
test "${clone_root}" = "/workspace/repository"
test ! -e "${clone_root}"
git clone --no-checkout -- "${remote_endpoint}" "${clone_root}"
test -d "${clone_root}/.git"
test ! -f "${clone_root}/.git"
test ! -e "${clone_root}/.git/objects/info/alternates"
git -C "${clone_root}" checkout --detach "${base_commit}"
observed_remote="$(git -C "${clone_root}" remote get-url origin)"
observed_format="$(git -C "${clone_root}" rev-parse --show-object-format)"
observed_head="$(git -C "${clone_root}" rev-parse --verify HEAD^{commit})"
observed_tree="$(git -C "${clone_root}" rev-parse --verify HEAD^{tree})"
test "${observed_remote}" = "${remote_endpoint}"
test "${observed_format}" = "${expected_object_format}"
test "${observed_head}" = "${base_commit}"
git -C "${clone_root}" fsck --no-dangling --no-reflogs
printf 'OPENZYME_REMOTE=%s\n' "${observed_remote}"
printf 'OPENZYME_OBJECT_FORMAT=%s\n' "${observed_format}"
printf 'OPENZYME_HEAD=%s\n' "${observed_head}"
printf 'OPENZYME_TREE=%s\n' "${observed_tree}"
printf 'OPENZYME_GIT_DIRECTORY=independent\n'
""".strip()
        environment = {
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {credential_token}",
        }
        result = self.executor.run(
            (
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
                f"{workspace.volume_id}:/workspace:rw,U",
                "--workdir",
                "/workspace",
                "--env",
                "GIT_CONFIG_COUNT",
                "--env",
                "GIT_CONFIG_KEY_0",
                "--env",
                "GIT_CONFIG_VALUE_0",
                workspace.image_ref,
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                script,
                "openzyme-clone",
                workspace.internal_git_endpoint,
                workspace.base_commit,
                workspace.object_format.value,
                workspace.clone_logical_root,
            ),
            environment=environment,
        )
        parsed = _parse_clone_output(result.stdout) if result.returncode == 0 else {}
        return AgentWorkspaceCloneResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            head_commit=parsed.get("OPENZYME_HEAD"),
            head_tree=parsed.get("OPENZYME_TREE"),
            object_format=(
                None
                if "OPENZYME_OBJECT_FORMAT" not in parsed
                else GitObjectFormat(parsed["OPENZYME_OBJECT_FORMAT"])
            ),
            remote_endpoint=parsed.get("OPENZYME_REMOTE"),
            independent_git_directory=(
                parsed.get("OPENZYME_GIT_DIRECTORY") == "independent"
            ),
        )


@dataclass(frozen=True, slots=True)
class AgentGitWorkspaceReadinessCandidate:
    workspace_id: str
    reservation_id: str
    reservation_fingerprint: str
    capability_lease_id: str
    capability_lease_intent_digest: str
    image_ref: str
    image_manifest_digest: str
    image_qualification_digest: str
    observation: AgentGitWorkspaceObservation
    candidate_digest: str
    schema_version: str = AGENT_GIT_WORKSPACE_READINESS_CANDIDATE_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        workspace: AgentGitWorkspace,
        observation: AgentGitWorkspaceObservation,
    ) -> AgentGitWorkspaceReadinessCandidate:
        payload = {
            "schema_version": AGENT_GIT_WORKSPACE_READINESS_CANDIDATE_SCHEMA_VERSION,
            "workspace_id": workspace.workspace_id,
            "reservation_id": workspace.reservation_id,
            "reservation_fingerprint": workspace.reservation_fingerprint,
            "capability_lease_id": workspace.capability_lease_id,
            "capability_lease_intent_digest": (
                workspace.capability_lease_intent_digest
            ),
            "image_ref": workspace.image_ref,
            "image_manifest_digest": workspace.image_manifest_digest,
            "image_qualification_digest": workspace.image_qualification_digest,
            "observation_digest": observation.observation_digest,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            workspace_id=workspace.workspace_id,
            reservation_id=workspace.reservation_id,
            reservation_fingerprint=workspace.reservation_fingerprint,
            capability_lease_id=workspace.capability_lease_id,
            capability_lease_intent_digest=(
                workspace.capability_lease_intent_digest
            ),
            image_ref=workspace.image_ref,
            image_manifest_digest=workspace.image_manifest_digest,
            image_qualification_digest=workspace.image_qualification_digest,
            observation=observation,
            candidate_digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        )


@dataclass(slots=True)
class AgentGitWorkspaceProvisioner:
    repositories: CoreRepositories
    volume_allocator: AgentWorkspaceVolumeAllocator
    clone_runner: AgentWorkspaceCloneRunner
    provision_credentials: RepositoryProvisionCredentialBroker
    namespace_retention: RepositoryPrivateNamespaceRetentionService
    provider_id: str = "agent_git_workspace_provisioner@1"
    _candidates: dict[str, AgentGitWorkspaceReadinessCandidate] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def provision_and_activate(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
        image_qualification: AgentCapsuleImageQualification,
        namespace_retention_deadline: str,
        actor_ref: str,
        workspace_id: str | None = None,
    ) -> AgentCapabilityIssuance:
        expected_manifest_digest = (
            load_agent_capsule_image_manifest().manifest_digest
        )
        if image_qualification.image_manifest_digest != expected_manifest_digest:
            raise AgentGitWorkspaceProvisioningError(
                "image qualification does not match the current capsule manifest"
            )
        resolved_workspace_id = (
            workspace_id or f"agent_git_workspace_{uuid4().hex}"
        )
        volume = self.volume_allocator.allocate(
            workspace_id=resolved_workspace_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        lifecycle = AgentGitWorkspaceLifecycleService(self.repositories)
        workspace = lifecycle.create_provisioning(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
            volume_id=volume.volume_id,
            clone_logical_root="/workspace/repository",
            image_qualification=image_qualification,
            workspace_id=resolved_workspace_id,
        )
        self._ensure_private_namespace(
            workspace,
            retention_deadline=namespace_retention_deadline,
        )
        issued = self.provision_credentials.issue(
            workspace_id=workspace.workspace_id,
            now=datetime.now(tz=UTC),
        )
        try:
            try:
                clone = self.clone_runner.clone_exact_base(
                    workspace=workspace,
                    credential_token=issued.token,
                )
            finally:
                self.provision_credentials.revoke(
                    issued.claims.credential_id,
                    revoked_at=datetime.now(tz=UTC).isoformat(),
                )
        except BaseException as exc:
            lifecycle.block(
                workspace_id=workspace.workspace_id,
                blocker_code=AgentGitWorkspaceBlockerCode.CLONE_FAILED,
                blocker_detail={
                    "exception_type": type(exc).__name__,
                    "reason": "clone_runner_failed_before_identity_observation",
                },
            )
            raise
        if clone.returncode != 0:
            lifecycle.block(
                workspace_id=workspace.workspace_id,
                blocker_code=AgentGitWorkspaceBlockerCode.CLONE_FAILED,
                blocker_detail={
                    "native_exit": clone.returncode,
                    "stderr_digest": _text_digest(clone.stderr),
                },
            )
            raise AgentGitWorkspaceProvisioningError(
                f"full clone failed with native exit {clone.returncode}"
            )
        observation = self._observation_from_clone(workspace, clone)
        comparison = lifecycle.compare_restore(
            workspace_id=workspace.workspace_id,
            observation=observation,
        )
        if not comparison.matches:
            lifecycle.block_from_restore_comparison(
                workspace_id=workspace.workspace_id,
                comparison=comparison,
            )
            raise AgentGitWorkspaceProvisioningError(
                "clone identity drifted from the canonical workspace"
            )
        candidate = AgentGitWorkspaceReadinessCandidate.create(
            workspace=workspace,
            observation=observation,
        )
        self._candidates[workspace.reservation_id] = candidate
        capability_service = AgentCapabilityLeaseService(
            repositories=self.repositories,
            readiness_providers={self.provider_id: self},
        )
        try:
            return capability_service.activate_with_provider(
                lease_id=workspace.capability_lease_id,
                provider_id=self.provider_id,
                actor_ref=actor_ref,
            )
        except BaseException:
            current = self.repositories.agent_git_workspaces.get(
                workspace.workspace_id
            )
            if current is not None and current.status is AgentGitWorkspaceStatus.PROVISIONING:
                lifecycle.block(
                    workspace_id=workspace.workspace_id,
                    blocker_code=AgentGitWorkspaceBlockerCode.PERSISTENCE_FAILED,
                    blocker_detail={
                        "candidate_digest": candidate.candidate_digest,
                        "reason": "atomic_readiness_activation_failed",
                    },
                )
            raise
        finally:
            self._candidates.pop(workspace.reservation_id, None)

    def verify_readiness(
        self,
        reservation: AgentWorkspaceGenerationReservation,
    ) -> AgentWorkspaceReadinessProof:
        candidate = self._require_candidate(reservation.reservation_id)
        if (
            candidate.reservation_fingerprint != reservation.immutable_fingerprint
            or candidate.observation.session_id != reservation.session_id
            or candidate.observation.agent_member_id != reservation.agent_member_id
            or candidate.observation.agent_id != reservation.agent_id
            or candidate.observation.workspace_generation
            != reservation.workspace_generation
        ):
            raise AgentGitWorkspaceProvisioningError(
                "readiness candidate does not match the exact C2 reservation"
            )
        return AgentWorkspaceReadinessProof(
            provider_id=self.provider_id,
            reservation_id=reservation.reservation_id,
            reservation_fingerprint=reservation.immutable_fingerprint,
            session_id=reservation.session_id,
            agent_member_id=reservation.agent_member_id,
            agent_id=reservation.agent_id,
            workspace_generation=reservation.workspace_generation,
            readiness_ref=f"agent_git_workspace:{candidate.workspace_id}",
            readiness_digest=candidate.candidate_digest,
            observed_at=candidate.observation.observed_at,
        )

    def stage_atomic_readiness(
        self,
        *,
        repositories: CoreRepositories,
        proof: AgentWorkspaceReadinessProof,
    ) -> AgentGitWorkspace:
        if repositories.tasks.connection is not self.repositories.tasks.connection:
            raise AgentGitWorkspaceProvisioningError(
                "atomic readiness must use the provisioner's canonical connection"
            )
        candidate = self._require_candidate(proof.reservation_id)
        if (
            proof.readiness_ref != f"agent_git_workspace:{candidate.workspace_id}"
            or proof.readiness_digest != candidate.candidate_digest
        ):
            raise AgentGitWorkspaceProvisioningError(
                "C2 readiness proof does not match the verified workspace candidate"
            )
        return AgentGitWorkspaceLifecycleService(
            repositories
        ).stage_ready_in_current_transaction(
            workspace_id=candidate.workspace_id,
            observation=candidate.observation,
        )

    def _ensure_private_namespace(
        self,
        workspace: AgentGitWorkspace,
        *,
        retention_deadline: str,
    ) -> None:
        connection = self.repositories.tasks.connection
        row = connection.execute(
            """
            SELECT namespace_prefix, status
            FROM repository_private_namespace_records
            WHERE binding_id = ?
              AND binding_version = ?
              AND session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (
                workspace.repository_binding_id,
                workspace.repository_binding_version,
                workspace.session_id,
                workspace.agent_member_id,
                workspace.workspace_generation,
            ),
        ).fetchone()
        if row is not None:
            if (
                row["status"] != "open"
                or row["namespace_prefix"] != workspace.private_ref_namespace
            ):
                raise AgentGitWorkspaceProvisioningError(
                    "existing private namespace does not match the workspace"
                )
            return
        binding = self.repositories.project_repository_bindings.get(
            workspace.repository_binding_id
        )
        pin = self.repositories.session_repository_binding_pins.require(
            workspace.session_id
        )
        if binding is None:
            raise AgentGitWorkspaceProvisioningError(
                "workspace repository binding disappeared before namespace creation"
            )
        self.namespace_retention.open_namespace(
            binding=binding,
            pin=pin,
            agent_member_id=workspace.agent_member_id,
            workspace_generation=workspace.workspace_generation,
            retention_deadline=retention_deadline,
            opened_at=datetime.now(tz=UTC).isoformat(),
            namespace_id=f"repository_namespace_{workspace.workspace_id}",
        )

    def _observation_from_clone(
        self,
        workspace: AgentGitWorkspace,
        clone: AgentWorkspaceCloneResult,
    ) -> AgentGitWorkspaceObservation:
        if (
            clone.head_commit is None
            or clone.head_tree is None
            or clone.object_format is None
            or clone.remote_endpoint is None
            or not clone.independent_git_directory
        ):
            raise AgentGitWorkspaceProvisioningError(
                "clone success did not return a complete independent Git identity"
            )
        return AgentGitWorkspaceObservation(
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            volume_id=workspace.volume_id,
            clone_logical_root=workspace.clone_logical_root,
            git_directory_kind=AgentGitDirectoryKind.INDEPENDENT,
            internal_git_service_id=workspace.internal_git_service_id,
            internal_git_endpoint=clone.remote_endpoint,
            repository_id=workspace.repository_id,
            object_format=clone.object_format,
            base_commit=workspace.base_commit,
            head_commit=clone.head_commit,
            head_tree=clone.head_tree,
            head_readable=True,
            private_ref_namespace=workspace.private_ref_namespace,
            repository_policy_digest=workspace.repository_policy_digest,
            capability_policy_digest=workspace.capability_policy_digest,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )

    def _require_candidate(
        self,
        reservation_id: str,
    ) -> AgentGitWorkspaceReadinessCandidate:
        candidate = self._candidates.get(reservation_id)
        if candidate is None:
            raise AgentGitWorkspaceProvisioningError(
                "workspace readiness candidate is missing or already consumed"
            )
        return candidate


def _parse_clone_output(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.startswith("OPENZYME_"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or not value or key in parsed:
            raise AgentGitWorkspaceProvisioningError(
                "clone runner returned ambiguous identity output"
            )
        parsed[key] = value
    required = {
        "OPENZYME_REMOTE",
        "OPENZYME_OBJECT_FORMAT",
        "OPENZYME_HEAD",
        "OPENZYME_TREE",
        "OPENZYME_GIT_DIRECTORY",
    }
    if set(parsed) != required:
        raise AgentGitWorkspaceProvisioningError(
            "clone runner omitted or added identity output fields"
        )
    return parsed


def _text_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


__all__ = [
    "AGENT_GIT_WORKSPACE_READINESS_CANDIDATE_SCHEMA_VERSION",
    "AgentGitWorkspaceProvisioner",
    "AgentGitWorkspaceProvisioningError",
    "AgentGitWorkspaceReadinessCandidate",
    "AgentWorkspaceCloneResult",
    "AgentWorkspaceCloneRunner",
    "PodmanAgentWorkspaceCloneRunner",
]
