from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
import hashlib
from importlib import resources
import json
import re
import threading
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceTransferDirection
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import require_workspace_relative_path

from .process import PodmanCommandExecutor
from .process import PodmanDispatchError
from .process import PodmanWorkspaceMount
from .process import PodmanWorkspaceMountResolver
from .process import SupervisedProcessRequest
from .process import SupervisedProcessResult
from .process import SupervisedSubprocessExecutor
from .process import build_podman_command


PODMAN_TRANSFER_PROVIDER_ID = "openzyme.transfer.podman"
PODMAN_TRANSFER_PROVIDER_CONTRACT = "openzyme.transfer.podman@1"
PODMAN_TRANSFER_HELPER_SCHEMA = "openzyme_workspace_transfer_helper@1"
PODMAN_TRANSFER_RESULT_SCHEMA = "openzyme_workspace_transfer_result@1"
_HELPER_RESOURCE = "assets/workspace_transfer_helper.py"
_SAFE_VOLUME_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _helper_source() -> str:
    return (
        resources.files("openzyme_process_podman")
        .joinpath(_HELPER_RESOURCE)
        .read_text(encoding="utf-8")
    )


PODMAN_TRANSFER_HELPER_DIGEST = (
    "sha256:41813efcf4fc77b3e65227da0b0d05ad054c4b66830bf9c69c9473a15745b561"
)
PODMAN_TRANSFER_PROVIDER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": PODMAN_TRANSFER_PROVIDER_CONTRACT,
        "helper_schema": PODMAN_TRANSFER_HELPER_SCHEMA,
        "helper_digest": PODMAN_TRANSFER_HELPER_DIGEST,
        "transport": "opaque_ref_to_second_named_volume",
        "directions": ["download", "sync_revision", "upload"],
        "path_policy": "root_relative_no_glob_symlink_or_hardlink_escape",
        "copy_policy": "create_only_atomic_content_verified",
        "network": "none",
        "fallback": False,
    }
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate transfer helper response key {key!r}")
        result[key] = value
    return result


class PodmanTransferObjectKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    REVISION_TREE = "revision_tree"


@dataclass(frozen=True, slots=True)
class PodmanRevisionTransferIdentity:
    source_kind: str
    source_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    source_ref: str
    commit: str
    tree: str
    source_digest: str
    lfs_closure_manifest_digest: str

    def __post_init__(self) -> None:
        if self.source_kind not in {"private_checkpoint", "published_revision"}:
            raise ValueError("revision transfer source kind is closed")
        for field_name in (
            "source_id",
            "repository_binding_id",
            "repository_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.repository_binding_version < 1:
            raise ValueError("repository binding version must be positive")
        if (
            not isinstance(self.source_ref, str)
            or not self.source_ref.startswith("refs/")
            or self.source_ref.endswith("/")
            or any(token in self.source_ref for token in ("..", "//", "@{"))
            or any(character.isspace() for character in self.source_ref)
        ):
            raise ValueError("source_ref must be one exact safe Git ref")
        for field_name in ("commit", "tree"):
            value = getattr(self, field_name)
            if _GIT_OBJECT_ID.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a lowercase Git object id")
        require_digest(self.source_digest, field_name="source_digest")
        require_digest(
            self.lfs_closure_manifest_digest,
            field_name="lfs_closure_manifest_digest",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "source_ref": self.source_ref,
            "commit": self.commit,
            "tree": self.tree,
            "source_digest": self.source_digest,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class PodmanTransferObjectMount:
    transfer_ref: str
    session_id: str
    owner_member_id: str
    workspace_id: str
    workspace_generation: int
    workspace_state_version: int
    direction: WorkspaceTransferDirection
    object_kind: PodmanTransferObjectKind
    max_bytes: int
    expected_content_digest: str | None
    expected_size_bytes: int | None
    revision_identity: PodmanRevisionTransferIdentity | None
    volume_id: str
    object_relative_path: str
    read_only: bool
    transfer_manifest_digest: str
    mount_manifest_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "transfer_ref",
            "session_id",
            "owner_member_id",
            "workspace_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if "/" in self.transfer_ref or "\\" in self.transfer_ref:
            raise ValueError("transfer_ref must remain opaque")
        if self.workspace_generation < 1 or self.workspace_state_version < 1:
            raise ValueError("workspace transfer generation/state must be positive")
        if not 1 <= self.max_bytes <= 68_719_476_736:
            raise ValueError("transfer max_bytes is outside the closed limit")
        if self.expected_content_digest is not None:
            require_digest(
                self.expected_content_digest,
                field_name="expected_content_digest",
            )
        if self.expected_size_bytes is not None and not (
            0 <= self.expected_size_bytes <= self.max_bytes
        ):
            raise ValueError("expected transfer size exceeds its byte budget")
        if _SAFE_VOLUME_NAME.fullmatch(self.volume_id) is None:
            raise ValueError("transfer volume is not one exact Podman named volume")
        object.__setattr__(
            self,
            "object_relative_path",
            require_workspace_relative_path(
                self.object_relative_path,
                field_name="object_relative_path",
            ),
        )
        if self.direction is WorkspaceTransferDirection.UPLOAD:
            if self.read_only:
                raise ValueError("upload transfer volume must be writable")
            if (
                self.object_kind is PodmanTransferObjectKind.REVISION_TREE
                or self.revision_identity is not None
            ):
                raise ValueError("upload cannot claim revision semantics")
        elif not self.read_only:
            raise ValueError("download/revision transfer source must be immutable")
        if self.direction is WorkspaceTransferDirection.SYNC_REVISION:
            if (
                self.object_kind is not PodmanTransferObjectKind.REVISION_TREE
                or self.revision_identity is None
            ):
                raise ValueError("revision sync requires an exact revision tree")
        elif (
            self.object_kind is PodmanTransferObjectKind.REVISION_TREE
            or self.revision_identity is not None
        ):
            raise ValueError("ordinary transfer cannot claim revision semantics")
        if self.direction is not WorkspaceTransferDirection.UPLOAD and (
            self.expected_content_digest is None or self.expected_size_bytes is None
        ):
            raise ValueError("immutable transfer source requires content identity")
        require_digest(
            self.transfer_manifest_digest,
            field_name="transfer_manifest_digest",
        )
        if self.transfer_manifest_digest != canonical_sha256_digest(
            self.transfer_contract_payload()
        ):
            raise ValueError("transfer manifest digest drifted")
        require_digest(
            self.mount_manifest_digest,
            field_name="mount_manifest_digest",
        )
        if self.mount_manifest_digest != canonical_sha256_digest(
            self.mount_identity_payload()
        ):
            raise ValueError("transfer mount digest drifted")

    def transfer_contract_payload(self) -> dict[str, object]:
        return {
            "schema_version": "podman_transfer_contract@1",
            "transfer_ref": self.transfer_ref,
            "session_id": self.session_id,
            "owner_member_id": self.owner_member_id,
            "workspace_id": self.workspace_id,
            "workspace_generation": self.workspace_generation,
            "workspace_state_version": self.workspace_state_version,
            "direction": self.direction.value,
            "object_kind": self.object_kind.value,
            "max_bytes": self.max_bytes,
            "expected_content_digest": self.expected_content_digest,
            "expected_size_bytes": self.expected_size_bytes,
            "revision_identity": (
                None
                if self.revision_identity is None
                else self.revision_identity.to_dict()
            ),
        }

    def mount_identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "podman_transfer_mount@1",
            "transfer_manifest_digest": self.transfer_manifest_digest,
            "volume_id": self.volume_id,
            "object_relative_path": self.object_relative_path,
            "read_only": self.read_only,
        }

    @classmethod
    def create(
        cls,
        *,
        transfer_ref: str,
        session_id: str,
        owner_member_id: str,
        workspace_id: str,
        workspace_generation: int,
        workspace_state_version: int,
        direction: WorkspaceTransferDirection,
        object_kind: PodmanTransferObjectKind,
        max_bytes: int,
        expected_content_digest: str | None,
        expected_size_bytes: int | None,
        revision_identity: PodmanRevisionTransferIdentity | None,
        volume_id: str,
        object_relative_path: str,
        read_only: bool,
    ) -> PodmanTransferObjectMount:
        contract_payload = {
            "schema_version": "podman_transfer_contract@1",
            "transfer_ref": transfer_ref,
            "session_id": session_id,
            "owner_member_id": owner_member_id,
            "workspace_id": workspace_id,
            "workspace_generation": workspace_generation,
            "workspace_state_version": workspace_state_version,
            "direction": direction.value,
            "object_kind": object_kind.value,
            "max_bytes": max_bytes,
            "expected_content_digest": expected_content_digest,
            "expected_size_bytes": expected_size_bytes,
            "revision_identity": (
                None if revision_identity is None else revision_identity.to_dict()
            ),
        }
        transfer_manifest_digest = canonical_sha256_digest(contract_payload)
        mount_payload = {
            "schema_version": "podman_transfer_mount@1",
            "transfer_manifest_digest": transfer_manifest_digest,
            "volume_id": volume_id,
            "object_relative_path": object_relative_path,
            "read_only": read_only,
        }
        return cls(
            transfer_ref=transfer_ref,
            session_id=session_id,
            owner_member_id=owner_member_id,
            workspace_id=workspace_id,
            workspace_generation=workspace_generation,
            workspace_state_version=workspace_state_version,
            direction=direction,
            object_kind=object_kind,
            max_bytes=max_bytes,
            expected_content_digest=expected_content_digest,
            expected_size_bytes=expected_size_bytes,
            revision_identity=revision_identity,
            volume_id=volume_id,
            object_relative_path=object_relative_path,
            read_only=read_only,
            transfer_manifest_digest=transfer_manifest_digest,
            mount_manifest_digest=canonical_sha256_digest(mount_payload),
        )

    def matches(self, request: WorkspaceTransferRequest) -> bool:
        binding = request.binding
        return (
            self.transfer_ref == request.transfer_ref
            and self.transfer_manifest_digest == request.transfer_manifest_digest
            and self.session_id == binding.session_id
            and self.owner_member_id == binding.owner_member_id
            and self.workspace_id == binding.workspace_id
            and self.workspace_generation == binding.generation
            and self.workspace_state_version == binding.state_version
            and self.direction is request.direction
            and self.max_bytes == request.max_bytes
        )


class PodmanTransferMountResolver(Protocol):
    def resolve(
        self,
        request: WorkspaceTransferRequest,
    ) -> PodmanTransferObjectMount | None: ...


@dataclass(frozen=True, slots=True)
class MappingPodmanTransferMountResolver:
    mounts: Mapping[str, PodmanTransferObjectMount]

    def resolve(
        self,
        request: WorkspaceTransferRequest,
    ) -> PodmanTransferObjectMount | None:
        mount = self.mounts.get(request.transfer_ref)
        return mount if mount is not None and mount.matches(request) else None


@dataclass(slots=True)
class PodmanWorkspaceTransferAdapter:
    workspace_mount_resolver: PodmanWorkspaceMountResolver
    transfer_mount_resolver: PodmanTransferMountResolver
    executor: PodmanCommandExecutor = field(default_factory=SupervisedSubprocessExecutor)
    podman_binary: str = "/usr/bin/podman"
    runtime_uid: int = 10_001
    runtime_gid: int = 10_001
    provider_id: str = PODMAN_TRANSFER_PROVIDER_ID
    provider_contract_digest: str = PODMAN_TRANSFER_PROVIDER_CONTRACT_DIGEST
    _receipts: dict[str, tuple[str, WorkspaceOperationReceipt]] = field(
        default_factory=dict
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _verified_helper_source: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.podman_binary.startswith("/") or "\x00" in self.podman_binary:
            raise ValueError("podman_binary must be one exact absolute executable path")
        if self.runtime_uid < 1 or self.runtime_gid < 1:
            raise ValueError("runtime uid/gid must be positive")
        if self.provider_id != PODMAN_TRANSFER_PROVIDER_ID:
            raise ValueError("Podman transfer provider identity is closed")
        if self.provider_contract_digest != PODMAN_TRANSFER_PROVIDER_CONTRACT_DIGEST:
            raise ValueError("Podman transfer contract digest is closed")
        helper_source = _helper_source()
        observed_helper_digest = (
            f"sha256:{hashlib.sha256(helper_source.encode('utf-8')).hexdigest()}"
        )
        if observed_helper_digest != PODMAN_TRANSFER_HELPER_DIGEST:
            raise ValueError("Podman transfer helper digest drifted")
        self._verified_helper_source = helper_source

    def transfer(self, request: WorkspaceTransferRequest) -> WorkspaceOperationReceipt:
        with self._lock:
            prior = self._receipts.get(request.operation_id)
            if prior is not None:
                if prior[0] != request.intent_digest:
                    raise WorkspacePortError(
                        "workspace_operation_identity_collision",
                        "operation identity was already used for another transfer",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                        mutation_applied=False,
                    )
                return prior[1]
        workspace_mount = self.workspace_mount_resolver.resolve(request.binding)
        transfer_mount = self.transfer_mount_resolver.resolve(request)
        if workspace_mount is None or transfer_mount is None:
            raise WorkspacePortError(
                "workspace_transfer_binding_stale",
                "the exact workspace or opaque transfer binding is unavailable",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        helper_request: dict[str, object] = {
            "schema_version": PODMAN_TRANSFER_HELPER_SCHEMA,
            "operation_id": request.operation_id,
            "intent_digest": request.intent_digest,
            "transfer_ref": request.transfer_ref,
            "transfer_manifest_digest": request.transfer_manifest_digest,
            "direction": request.direction.value,
            "workspace_path": request.path,
            "transfer_path": transfer_mount.object_relative_path,
            "object_kind": transfer_mount.object_kind.value,
            "max_bytes": request.max_bytes,
            "expected_content_digest": transfer_mount.expected_content_digest,
            "expected_size_bytes": transfer_mount.expected_size_bytes,
            "revision_identity": (
                None
                if transfer_mount.revision_identity is None
                else transfer_mount.revision_identity.to_dict()
            ),
        }
        response = self._invoke(
            request=request,
            workspace_mount=workspace_mount,
            transfer_mount=transfer_mount,
            helper_request=helper_request,
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise WorkspacePortError(
                "workspace_transfer_result_invalid",
                "transfer helper returned an invalid result",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )
        self._validate_result(request, transfer_mount, result)
        result_payload = _json_bytes(
            {
                "schema_version": PODMAN_TRANSFER_RESULT_SCHEMA,
                **result,
            }
        )
        receipt = WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=result_payload,
        )
        with self._lock:
            self._receipts[request.operation_id] = (request.intent_digest, receipt)
        return receipt

    def reconcile(
        self,
        request: WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        """Observe an exact transfer receipt without copying bytes again."""

        with self._lock:
            prior = self._receipts.get(request.operation_id)
        if prior is not None:
            if prior[0] != request.intent_digest:
                raise WorkspacePortError(
                    "workspace_operation_identity_collision",
                    "operation identity was already used for another transfer",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    mutation_applied=False,
                )
            return prior[1]
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            mutation_applied=None,
            diagnostic_id="diagnostic-transfer-reconciliation-pending",
        )

    def _invoke(
        self,
        *,
        request: WorkspaceTransferRequest,
        workspace_mount: PodmanWorkspaceMount,
        transfer_mount: PodmanTransferObjectMount,
        helper_request: dict[str, object],
    ) -> dict[str, object]:
        process_identity = (
            "ozxfer-" + request.intent_digest.removeprefix("sha256:")[:24]
        )
        command = list(
            build_podman_command(
                podman_binary=self.podman_binary,
                deployment_network="none",
                runtime_uid=self.runtime_uid,
                runtime_gid=self.runtime_gid,
                mount=workspace_mount,
                process_identity=process_identity,
                cwd_relative=".",
                environment_keys=(),
                timeout_seconds=request.timeout_seconds,
                argv=(
                    "/usr/bin/python3",
                    "-c",
                    self._verified_helper_source,
                    "/openzyme-transfer",
                ),
            )
        )
        image_index = command.index(workspace_mount.image_identity)
        command[image_index:image_index] = [
            "--mount",
            (
                f"type=volume,src={transfer_mount.volume_id},"
                f"dst=/openzyme-transfer,"
                f"{'ro' if transfer_mount.read_only else 'rw'}"
            ),
        ]
        try:
            result = self.executor.run(
                SupervisedProcessRequest(
                    process_identity=process_identity,
                    process_epoch=request.authority_generation,
                    authority_fence=request.authority_fence,
                    argv=tuple(command),
                    environment={},
                    stdin=_json_bytes(helper_request),
                    timeout_seconds=request.timeout_seconds + 10,
                    max_output_bytes=65_536,
                )
            )
        except PodmanDispatchError as exc:
            self._raise_adapter_error(exc.error_code, exc.effect_certainty)
        except Exception as exc:
            raise WorkspacePortError(
                "workspace_transfer_dispatch_unclassified",
                "transfer outcome is uncertain",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            ) from exc
        return self._parse_response(result)

    def _parse_response(
        self,
        result: SupervisedProcessResult,
    ) -> dict[str, object]:
        if (
            result.timed_out
            or result.returncode != 0
            or result.stdout_truncated
            or result.stderr_truncated
        ):
            self._raise_adapter_error(
                "workspace_transfer_process_unsettled",
                ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        try:
            response = json.loads(
                result.stdout,
                object_pairs_hook=_unique_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite transfer response {value}")
                ),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkspacePortError(
                "workspace_transfer_response_invalid",
                "transfer helper returned an invalid closed response",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            ) from exc
        if not isinstance(response, dict) or response.get("schema_version") != (
            PODMAN_TRANSFER_HELPER_SCHEMA
        ):
            self._raise_adapter_error(
                "workspace_transfer_response_invalid",
                ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        if response.get("ok") is not True:
            error_code = response.get("error_code")
            try:
                certainty = ExternalEffectCertainty(
                    str(response.get("effect_certainty"))
                )
            except ValueError:
                certainty = ExternalEffectCertainty.DISPATCH_IN_DOUBT
            self._raise_adapter_error(
                (
                    str(error_code)
                    if isinstance(error_code, str)
                    else "workspace_transfer_rejected"
                ),
                certainty,
            )
        if (
            response.get("effect_certainty") != "terminal_known"
            or response.get("mutation_applied") is not True
        ):
            self._raise_adapter_error(
                "workspace_transfer_receipt_mismatch",
                ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        return response

    @staticmethod
    def _validate_result(
        request: WorkspaceTransferRequest,
        transfer_mount: PodmanTransferObjectMount,
        result: dict[str, object],
    ) -> None:
        exact_fields = {
            "transfer_ref",
            "transfer_manifest_digest",
            "direction",
            "workspace_path",
            "object_kind",
            "content_digest",
            "size_bytes",
            "entry_count",
            "revision_identity",
            "replayed",
            "checkpoint_performed",
            "publication_performed",
            "workspace_cleanup_performed",
            "task_transition_performed",
            "fallback_performed",
        }
        if set(result) != exact_fields:
            raise WorkspacePortError(
                "workspace_transfer_result_invalid",
                "transfer result is not one closed schema",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )
        revision_identity = (
            None
            if transfer_mount.revision_identity is None
            else transfer_mount.revision_identity.to_dict()
        )
        if (
            result["transfer_ref"] != request.transfer_ref
            or result["transfer_manifest_digest"]
            != request.transfer_manifest_digest
            or result["direction"] != request.direction.value
            or result["workspace_path"] != request.path
            or result["object_kind"] != transfer_mount.object_kind.value
            or result["revision_identity"] != revision_identity
            or result["checkpoint_performed"] is not False
            or result["publication_performed"] is not False
            or result["workspace_cleanup_performed"] is not False
            or result["task_transition_performed"] is not False
            or result["fallback_performed"] is not False
            or not isinstance(result["replayed"], bool)
            or not isinstance(result["size_bytes"], int)
            or isinstance(result["size_bytes"], bool)
            or not 0 <= result["size_bytes"] <= request.max_bytes
            or not isinstance(result["entry_count"], int)
            or isinstance(result["entry_count"], bool)
            or result["entry_count"] < 0
            or (
                transfer_mount.object_kind is PodmanTransferObjectKind.FILE
                and result["entry_count"] != 1
            )
            or not isinstance(result["content_digest"], str)
        ):
            raise WorkspacePortError(
                "workspace_transfer_result_identity_mismatch",
                "transfer result does not bind the exact request",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )
        try:
            require_digest(
                str(result["content_digest"]),
                field_name="content_digest",
            )
        except (TypeError, ValueError) as exc:
            raise WorkspacePortError(
                "workspace_transfer_result_identity_mismatch",
                "transfer result content identity is invalid",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            ) from exc
        if (
            transfer_mount.expected_content_digest is not None
            and result["content_digest"]
            != transfer_mount.expected_content_digest
        ) or (
            transfer_mount.expected_size_bytes is not None
            and result["size_bytes"] != transfer_mount.expected_size_bytes
        ):
            raise WorkspacePortError(
                "workspace_transfer_result_content_mismatch",
                "transfer result differs from the reserved content identity",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )

    @staticmethod
    def _raise_adapter_error(
        error_code: str,
        certainty: ExternalEffectCertainty,
    ) -> None:
        mutation_applied = (
            False
            if certainty is ExternalEffectCertainty.NO_EFFECT
            else None
            if certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else True
        )
        raise WorkspacePortError(
            error_code,
            "the selected Podman transfer Adapter rejected the operation",
            effect_certainty=certainty,
            mutation_applied=mutation_applied,
        )


__all__ = [
    "MappingPodmanTransferMountResolver",
    "PODMAN_TRANSFER_HELPER_DIGEST",
    "PODMAN_TRANSFER_HELPER_SCHEMA",
    "PODMAN_TRANSFER_PROVIDER_CONTRACT",
    "PODMAN_TRANSFER_PROVIDER_CONTRACT_DIGEST",
    "PODMAN_TRANSFER_PROVIDER_ID",
    "PODMAN_TRANSFER_RESULT_SCHEMA",
    "PodmanRevisionTransferIdentity",
    "PodmanTransferMountResolver",
    "PodmanTransferObjectKind",
    "PodmanTransferObjectMount",
    "PodmanWorkspaceTransferAdapter",
]
