from __future__ import annotations

import base64
from dataclasses import dataclass
from dataclasses import field
import hashlib
from importlib import resources
import json
import threading
from typing import Any

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import canonical_sha256_digest

from .process import PodmanCommandExecutor
from .process import PodmanDispatchError
from .process import PodmanWorkspaceMount
from .process import PodmanWorkspaceMountResolver
from .process import SupervisedProcessRequest
from .process import SupervisedProcessResult
from .process import SupervisedSubprocessExecutor
from .process import build_podman_command


PODMAN_FILESYSTEM_PROVIDER_ID = "openzyme.filesystem.podman"
PODMAN_FILESYSTEM_PROVIDER_CONTRACT = "openzyme.filesystem.podman@1"
PODMAN_FILESYSTEM_HELPER_SCHEMA = "openzyme_workspace_fs_helper@1"
_HELPER_RESOURCE = "assets/workspace_fs_helper.py"


def _helper_source() -> str:
    return (
        resources.files("openzyme_process_podman")
        .joinpath(_HELPER_RESOURCE)
        .read_text(encoding="utf-8")
    )


PODMAN_FILESYSTEM_HELPER_DIGEST = (
    "sha256:df7ddadb8a3aebc6d252ac583d88c621209622ed4f5d262d5d91a7f4d841ca9b"
)
PODMAN_FILESYSTEM_PROVIDER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": PODMAN_FILESYSTEM_PROVIDER_CONTRACT,
        "helper_schema": PODMAN_FILESYSTEM_HELPER_SCHEMA,
        "helper_digest": PODMAN_FILESYSTEM_HELPER_DIGEST,
        "path_policy": "root_relative_no_glob_symlink_or_hardlink_escape",
        "mutation_policy": "cas_precondition_and_atomic_replace",
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
            raise ValueError(f"duplicate helper response key {key!r}")
        result[key] = value
    return result


@dataclass(slots=True)
class PodmanWorkspaceFilesystemAdapter:
    mount_resolver: PodmanWorkspaceMountResolver
    executor: PodmanCommandExecutor = field(default_factory=SupervisedSubprocessExecutor)
    podman_binary: str = "/usr/bin/podman"
    runtime_uid: int = 10_001
    runtime_gid: int = 10_001
    provider_id: str = PODMAN_FILESYSTEM_PROVIDER_ID
    provider_contract_digest: str = PODMAN_FILESYSTEM_PROVIDER_CONTRACT_DIGEST
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
        if self.provider_id != PODMAN_FILESYSTEM_PROVIDER_ID:
            raise ValueError("Podman filesystem provider identity is closed")
        if self.provider_contract_digest != PODMAN_FILESYSTEM_PROVIDER_CONTRACT_DIGEST:
            raise ValueError("Podman filesystem contract digest is closed")
        helper_source = _helper_source()
        observed_helper_digest = (
            f"sha256:{hashlib.sha256(helper_source.encode('utf-8')).hexdigest()}"
        )
        if observed_helper_digest != PODMAN_FILESYSTEM_HELPER_DIGEST:
            raise ValueError("Podman filesystem helper digest drifted")
        self._verified_helper_source = helper_source

    def observe(self, request: WorkspaceObservationRequest) -> WorkspaceObservation:
        mount = self._require_mount(request.binding)
        helper_request = {
            "schema_version": PODMAN_FILESYSTEM_HELPER_SCHEMA,
            "mode": "observation",
            "operation": request.operation.value,
            "path": request.path,
            "max_bytes": request.max_bytes,
            "query_digest": request.query_digest,
        }
        response = self._invoke(
            mount=mount,
            process_identity=(
                "ozfsq-" + request.query_digest.removeprefix("sha256:")[:24]
            ),
            process_epoch=request.binding.generation,
            authority_fence=request.binding.state_version,
            helper_request=helper_request,
            timeout_seconds=30,
            max_output_bytes=min(4_194_304, request.max_bytes + 65_536),
            mutating=False,
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise WorkspacePortError(
                "workspace_helper_result_invalid",
                "filesystem helper returned an invalid observation result",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        payload = _json_bytes(result)
        if len(payload) > request.max_bytes:
            raise WorkspacePortError(
                "workspace_observation_result_unbounded",
                "filesystem observation exceeded its declared output budget",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        return WorkspaceObservation(
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            operation=request.operation,
            result_digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            bounded_payload=payload,
        )

    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        with self._lock:
            prior = self._receipts.get(request.operation_id)
            if prior is not None:
                if prior[0] != request.intent_digest:
                    raise WorkspacePortError(
                        "workspace_operation_identity_collision",
                        "operation identity was already used for another intent",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                        mutation_applied=False,
                    )
                return prior[1]
        mount = self._require_mount(request.binding)
        helper_request = {
            "schema_version": PODMAN_FILESYSTEM_HELPER_SCHEMA,
            "mode": "mutation",
            "operation": request.operation.value,
            "path": request.path,
            "destination_path": request.destination_path,
            "content_base64": (
                None
                if request.content is None
                else base64.b64encode(request.content).decode("ascii")
            ),
            "expected_content_digest": request.expected_content_digest,
            "recursive": request.recursive,
            "operation_id": request.operation_id,
            "intent_digest": request.intent_digest,
            "authority_lease_id": request.authority_lease_id,
            "authority_generation": request.authority_generation,
            "authority_fence": request.authority_fence,
        }
        response = self._invoke(
            mount=mount,
            process_identity=(
                "ozfsm-" + request.intent_digest.removeprefix("sha256:")[:24]
            ),
            process_epoch=request.authority_generation,
            authority_fence=request.authority_fence,
            helper_request=helper_request,
            timeout_seconds=60,
            max_output_bytes=65_536,
            mutating=True,
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise WorkspacePortError(
                "workspace_helper_result_invalid",
                "filesystem helper returned an invalid mutation result",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
            )
        receipt = WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=_json_bytes(result),
        )
        with self._lock:
            self._receipts[request.operation_id] = (request.intent_digest, receipt)
        return receipt

    def reconcile(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        """Return observed receipt state without invoking the mutation helper."""

        with self._lock:
            prior = self._receipts.get(request.operation_id)
        if prior is not None:
            if prior[0] != request.intent_digest:
                raise WorkspacePortError(
                    "workspace_operation_identity_collision",
                    "operation identity was already used for another intent",
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
            diagnostic_id="diagnostic-filesystem-reconciliation-pending",
        )

    def _require_mount(self, binding: Any) -> PodmanWorkspaceMount:
        mount = self.mount_resolver.resolve(binding)
        if mount is None:
            raise WorkspacePortError(
                "podman_workspace_mount_stale",
                "the exact local workspace mount is unavailable",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
            )
        return mount

    def _invoke(
        self,
        *,
        mount: PodmanWorkspaceMount,
        process_identity: str,
        process_epoch: int,
        authority_fence: int,
        helper_request: dict[str, object],
        timeout_seconds: int,
        max_output_bytes: int,
        mutating: bool,
    ) -> dict[str, object]:
        command = build_podman_command(
            podman_binary=self.podman_binary,
            deployment_network="none",
            runtime_uid=self.runtime_uid,
            runtime_gid=self.runtime_gid,
            mount=mount,
            process_identity=process_identity,
            cwd_relative=".",
            environment_keys=(),
            timeout_seconds=timeout_seconds,
            argv=("/usr/bin/python3", "-c", self._verified_helper_source),
        )
        try:
            result = self.executor.run(
                SupervisedProcessRequest(
                    process_identity=process_identity,
                    process_epoch=process_epoch,
                    authority_fence=authority_fence,
                    argv=command,
                    environment={},
                    stdin=_json_bytes(helper_request),
                    timeout_seconds=timeout_seconds + 10,
                    max_output_bytes=max_output_bytes,
                )
            )
        except PodmanDispatchError as exc:
            self._raise_adapter_error(
                exc.error_code,
                exc.effect_certainty,
                mutating=mutating,
            )
        except Exception as exc:
            raise WorkspacePortError(
                "workspace_helper_dispatch_unclassified",
                "filesystem helper outcome is uncertain",
                effect_certainty=(
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if mutating
                    else ExternalEffectCertainty.NO_EFFECT
                ),
                mutation_applied=None if mutating else False,
            ) from exc
        return self._parse_response(result, mutating=mutating)

    def _parse_response(
        self,
        result: SupervisedProcessResult,
        *,
        mutating: bool,
    ) -> dict[str, object]:
        if (
            result.timed_out
            or result.returncode != 0
            or result.stdout_truncated
            or result.stderr_truncated
        ):
            self._raise_adapter_error(
                "workspace_helper_process_unsettled",
                (
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if mutating
                    else ExternalEffectCertainty.NO_EFFECT
                ),
                mutating=mutating,
            )
        try:
            response = json.loads(
                result.stdout,
                object_pairs_hook=_unique_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite helper response {value}")
                ),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkspacePortError(
                "workspace_helper_response_invalid",
                "filesystem helper returned an invalid closed response",
                effect_certainty=(
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if mutating
                    else ExternalEffectCertainty.NO_EFFECT
                ),
                mutation_applied=None if mutating else False,
            ) from exc
        if not isinstance(response, dict) or response.get("schema_version") != (
            PODMAN_FILESYSTEM_HELPER_SCHEMA
        ):
            self._raise_adapter_error(
                "workspace_helper_response_invalid",
                (
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if mutating
                    else ExternalEffectCertainty.NO_EFFECT
                ),
                mutating=mutating,
            )
        if response.get("ok") is not True:
            error_code = response.get("error_code")
            certainty_text = response.get("effect_certainty")
            try:
                certainty = ExternalEffectCertainty(str(certainty_text))
            except ValueError:
                certainty = (
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if mutating
                    else ExternalEffectCertainty.NO_EFFECT
                )
            self._raise_adapter_error(
                (
                    str(error_code)
                    if isinstance(error_code, str)
                    else "workspace_helper_rejected"
                ),
                certainty,
                mutating=mutating,
            )
        if response.get("effect_certainty") != (
            "terminal_known" if mutating else "no_effect"
        ) or response.get("mutation_applied") is not mutating:
            self._raise_adapter_error(
                "workspace_helper_receipt_mismatch",
                (
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if mutating
                    else ExternalEffectCertainty.NO_EFFECT
                ),
                mutating=mutating,
            )
        return response

    @staticmethod
    def _raise_adapter_error(
        error_code: str,
        certainty: ExternalEffectCertainty,
        *,
        mutating: bool,
    ) -> None:
        if not mutating:
            certainty = ExternalEffectCertainty.NO_EFFECT
        mutation_applied = (
            False
            if certainty is ExternalEffectCertainty.NO_EFFECT
            else None
            if certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else True
        )
        raise WorkspacePortError(
            error_code,
            "the selected Podman filesystem Adapter rejected the operation",
            effect_certainty=certainty,
            mutation_applied=mutation_applied,
        )


__all__ = [
    "PODMAN_FILESYSTEM_HELPER_DIGEST",
    "PODMAN_FILESYSTEM_HELPER_SCHEMA",
    "PODMAN_FILESYSTEM_PROVIDER_CONTRACT",
    "PODMAN_FILESYSTEM_PROVIDER_CONTRACT_DIGEST",
    "PODMAN_FILESYSTEM_PROVIDER_ID",
    "PodmanWorkspaceFilesystemAdapter",
]
