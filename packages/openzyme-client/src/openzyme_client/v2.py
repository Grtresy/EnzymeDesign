from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
import json
from typing import Any
from typing import Protocol

from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspaceExtensionSectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


class OpenZymeClientContractError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        mutation_applied: bool | None = False,
        effect_certainty: str = "no_effect",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.mutation_applied = mutation_applied
        self.effect_certainty = effect_certainty
        self.fallback_performed = False


@dataclass(frozen=True, slots=True)
class ClientHttpRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class ClientHttpResponse:
    status_code: int
    media_type: str
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class ClientHttpTransportPort(Protocol):
    def send(self, request: ClientHttpRequest) -> ClientHttpResponse: ...


@dataclass(frozen=True, slots=True)
class VerifiedServerContract:
    release_digest: str
    public_contract_digest: str
    projection_digest: str
    capability_binding_digest: str
    affordance_snapshot_digest: str


class OpenZymeV2Client:
    def __init__(
        self,
        *,
        transport: ClientHttpTransportPort,
        expected_release: LayeredReleaseIdentity,
    ) -> None:
        self._transport = transport
        self._expected_release = expected_release

    def bootstrap_session(
        self,
        *,
        authorization: str,
        idempotency_key: str,
        body: bytes,
    ) -> ClientHttpResponse:
        """Create the first Session graph without inventing projection facts."""

        require_identifier(idempotency_key, field_name="idempotency_key")
        response = self._transport.send(
            ClientHttpRequest(
                method="POST",
                path="/v3/sessions",
                headers={
                    "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                    "Content-Type": "application/json",
                    "Authorization": authorization,
                    "Idempotency-Key": idempotency_key,
                    "OpenZyme-Workspace-Contract": (
                        FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                    ),
                    "OpenZyme-Release-Digest": (
                        self._expected_release.release_digest
                    ),
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                },
                body=body,
            )
        )
        _verify_pre_session_mutation_response(
            response,
            expected_release=self._expected_release,
        )
        return response

    def inspect_workspace(
        self,
        *,
        session_id: str,
        authorization: str,
    ) -> tuple[FileWorkspacePublicV2, VerifiedServerContract]:
        require_identifier(session_id, field_name="session_id")
        response = self._transport.send(
            ClientHttpRequest(
                method="GET",
                path=f"/v3/sessions/{session_id}/workspace",
                headers={
                    "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                    "Authorization": authorization,
                    "OpenZyme-Workspace-Contract": (
                        FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                    ),
                },
            )
        )
        projection = parse_file_workspace_public_v2(
            response,
            expected_release=self._expected_release,
        )
        binding_digest, snapshot_digest = _mutation_scope_digests(projection)
        return projection, VerifiedServerContract(
            release_digest=projection.release.release_digest,
            public_contract_digest=FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
            projection_digest=projection.projection_digest,
            capability_binding_digest=binding_digest,
            affordance_snapshot_digest=snapshot_digest,
        )

    def send_mutation(
        self,
        *,
        method: str,
        path: str,
        authorization: str,
        idempotency_key: str,
        body: bytes,
        verified_contract: VerifiedServerContract,
        capability_binding_digest: str,
        affordance_snapshot_digest: str,
    ) -> ClientHttpResponse:
        if verified_contract.release_digest != self._expected_release.release_digest:
            raise OpenZymeClientContractError(
                "client_release_identity_stale",
                "verified server release differs from the configured client release",
            )
        if (
            verified_contract.public_contract_digest
            != FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
        ):
            raise OpenZymeClientContractError(
                "client_public_contract_stale",
                "verified server public contract differs from the client contract",
            )
        if (
            capability_binding_digest
            != verified_contract.capability_binding_digest
        ):
            raise OpenZymeClientContractError(
                "client_capability_binding_stale",
                "mutation capability binding differs from the inspected workspace",
            )
        if (
            affordance_snapshot_digest
            != verified_contract.affordance_snapshot_digest
        ):
            raise OpenZymeClientContractError(
                "client_affordance_snapshot_stale",
                "mutation affordance snapshot differs from the inspected turn",
            )
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("mutation method is not supported")
        if not path.startswith("/v3/") or ".." in path or "\x00" in path:
            raise ValueError("mutation path is not one bounded V3 path")
        require_identifier(idempotency_key, field_name="idempotency_key")
        response = self._transport.send(
            ClientHttpRequest(
                method=method,
                path=path,
                headers={
                    "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                    "Content-Type": "application/json",
                    "Authorization": authorization,
                    "Idempotency-Key": idempotency_key,
                    "OpenZyme-Workspace-Contract": (
                        FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                    ),
                    "OpenZyme-Release-Digest": verified_contract.release_digest,
                    "OpenZyme-Public-Contract-Digest": (
                        verified_contract.public_contract_digest
                    ),
                    "OpenZyme-Projection-Digest": (
                        verified_contract.projection_digest
                    ),
                    "OpenZyme-Capability-Binding-Digest": (
                        verified_contract.capability_binding_digest
                    ),
                    "OpenZyme-Affordance-Snapshot-Digest": (
                        verified_contract.affordance_snapshot_digest
                    ),
                },
                body=body,
            )
        )
        _verify_mutation_response(
            response,
            verified_contract=verified_contract,
        )
        return response


def parse_file_workspace_public_v2(
    response: ClientHttpResponse,
    *,
    expected_release: LayeredReleaseIdentity,
) -> FileWorkspacePublicV2:
    if response.status_code != 200:
        raise OpenZymeClientContractError(
            "client_workspace_inspection_failed",
            f"workspace inspection returned HTTP {response.status_code}",
        )
    if response.media_type != FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE:
        raise OpenZymeClientContractError(
            "client_workspace_media_type_mismatch",
            "workspace response media type is not file_workspace_public@2",
        )
    response_headers = {
        str(name).strip().lower(): str(value).strip()
        for name, value in response.headers.items()
    }
    _verify_response_header(
        response_headers,
        "openzyme-workspace-contract",
        FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
    )
    _verify_response_header(
        response_headers,
        "openzyme-release-digest",
        expected_release.release_digest,
    )
    _verify_response_header(
        response_headers,
        "openzyme-public-contract-digest",
        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
    )
    try:
        value = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenZymeClientContractError(
            "client_workspace_payload_invalid",
            "workspace response is not valid UTF-8 JSON",
        ) from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "release",
        "core",
        "extensions",
    }:
        raise OpenZymeClientContractError(
            "client_workspace_payload_invalid",
            "workspace response root is not closed",
        )
    if value["schema_version"] != FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION:
        raise OpenZymeClientContractError(
            "client_workspace_contract_mismatch",
            "workspace response schema is not file_workspace_public@2",
        )
    _verify_release(value["release"], expected_release=expected_release)
    try:
        core = FileWorkspaceCoreProjectionV2(_mapping(value["core"], "core"))
        raw_extensions = _mapping(value["extensions"], "extensions")
        extensions = tuple(
            _parse_extension_section(section_id, section)
            for section_id, section in raw_extensions.items()
        )
        projection = FileWorkspacePublicV2(
            release=expected_release,
            core=core,
            extensions=extensions,
        )
    except (TypeError, ValueError) as exc:
        raise OpenZymeClientContractError(
            "client_workspace_payload_invalid",
            "workspace response failed closed schema or digest validation",
        ) from exc
    binding_digest, snapshot_digest = _mutation_scope_digests(projection)
    for header_name, expected_value in (
        ("openzyme-projection-digest", projection.projection_digest),
        ("openzyme-capability-binding-digest", binding_digest),
        ("openzyme-affordance-snapshot-digest", snapshot_digest),
    ):
        _verify_response_header(response_headers, header_name, expected_value)
    return projection


def _verify_response_header(
    headers: Mapping[str, str],
    header_name: str,
    expected_value: str,
) -> None:
    if headers.get(header_name) != expected_value:
        raise OpenZymeClientContractError(
            "client_response_identity_mismatch",
            f"workspace response header {header_name!r} is absent or stale",
        )


def _verify_mutation_response(
    response: ClientHttpResponse,
    *,
    verified_contract: VerifiedServerContract,
) -> None:
    if response.status_code >= 400:
        raise OpenZymeClientContractError(
            "client_mutation_failed",
            f"Host mutation returned HTTP {response.status_code}",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        )
    headers = {
        str(name).strip().lower(): str(value).strip()
        for name, value in response.headers.items()
    }
    for header_name, expected_value in (
        ("openzyme-workspace-contract", FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION),
        ("openzyme-release-digest", verified_contract.release_digest),
        (
            "openzyme-public-contract-digest",
            verified_contract.public_contract_digest,
        ),
        ("openzyme-projection-digest", verified_contract.projection_digest),
        (
            "openzyme-capability-binding-digest",
            verified_contract.capability_binding_digest,
        ),
        (
            "openzyme-affordance-snapshot-digest",
            verified_contract.affordance_snapshot_digest,
        ),
    ):
        if headers.get(header_name) != expected_value:
            raise OpenZymeClientContractError(
                "client_mutation_response_identity_mismatch",
                f"mutation response header {header_name!r} is absent or stale",
                mutation_applied=None,
                effect_certainty="dispatch_in_doubt",
            )


def _verify_pre_session_mutation_response(
    response: ClientHttpResponse,
    *,
    expected_release: LayeredReleaseIdentity,
) -> None:
    if response.status_code >= 400:
        raise OpenZymeClientContractError(
            "client_session_bootstrap_failed",
            f"Host Session bootstrap returned HTTP {response.status_code}",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        )
    headers = {
        str(name).strip().lower(): str(value).strip()
        for name, value in response.headers.items()
    }
    for header_name, expected_value in (
        ("openzyme-workspace-contract", FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION),
        ("openzyme-release-digest", expected_release.release_digest),
        (
            "openzyme-public-contract-digest",
            FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
        ),
    ):
        if headers.get(header_name) != expected_value:
            raise OpenZymeClientContractError(
                "client_session_bootstrap_response_identity_mismatch",
                f"Session bootstrap response header {header_name!r} is absent or stale",
                mutation_applied=None,
                effect_certainty="dispatch_in_doubt",
            )


def _verify_release(value: object, *, expected_release: LayeredReleaseIdentity) -> None:
    release = _mapping(value, "release")
    expected = {
        **expected_release.to_dict(),
        "release_digest": expected_release.release_digest,
        "public_contract_digest": FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
    }
    if release != expected:
        raise OpenZymeClientContractError(
            "client_release_identity_mismatch",
            "workspace release identity differs from the configured exact release",
        )


def _mutation_scope_digests(
    projection: FileWorkspacePublicV2,
) -> tuple[str, str]:
    core = projection.core.payload
    binding = _mapping(core["capability_binding"], "core.capability_binding")
    reflection = _mapping(core["tool_reflection"], "core.tool_reflection")
    binding_digest = binding.get("binding_digest")
    reflected_binding_digest = reflection.get("capability_binding_digest")
    snapshot_digest = reflection.get("affordance_snapshot_digest")
    if (
        not isinstance(binding_digest, str)
        or reflected_binding_digest != binding_digest
        or not isinstance(snapshot_digest, str)
    ):
        raise OpenZymeClientContractError(
            "client_mutation_scope_identity_invalid",
            "workspace projection lacks one exact binding and affordance identity",
        )
    try:
        require_digest(binding_digest, field_name="capability_binding_digest")
        require_digest(snapshot_digest, field_name="affordance_snapshot_digest")
    except ValueError as exc:
        raise OpenZymeClientContractError(
            "client_mutation_scope_identity_invalid",
            "workspace binding or affordance identity is not canonical",
        ) from exc
    return binding_digest, snapshot_digest


def _parse_extension_section(
    section_id: str,
    value: JsonObject,
) -> FileWorkspaceExtensionSectionV2:
    section = _mapping(value, f"extensions.{section_id}")
    if set(section) != {
        "section_contract_digest",
        "payload",
        "next_cursor",
        "projection_digest",
    }:
        raise ValueError("extension section fields are closed")
    return FileWorkspaceExtensionSectionV2(
        section_id=section_id,
        section_contract_digest=str(section["section_contract_digest"]),
        payload=_mapping(section["payload"], f"extensions.{section_id}.payload"),
        next_cursor=section["next_cursor"],
        projection_digest=str(section["projection_digest"]),
    )


JsonObject = Mapping[str, Any]


def _mapping(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


__all__ = [
    "ClientHttpRequest",
    "ClientHttpResponse",
    "ClientHttpTransportPort",
    "OpenZymeClientContractError",
    "OpenZymeV2Client",
    "VerifiedServerContract",
    "parse_file_workspace_public_v2",
]
