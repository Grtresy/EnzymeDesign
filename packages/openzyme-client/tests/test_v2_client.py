import json

import pytest

from openzyme_client import ClientHttpRequest
from openzyme_client import ClientHttpResponse
from openzyme_client import OpenZymeClientContractError
from openzyme_client import OpenZymeV2Client
from openzyme_client import VerifiedServerContract
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("core-schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )


class _Transport:
    def __init__(self, response: ClientHttpResponse) -> None:
        self.response = response
        self.requests: list[ClientHttpRequest] = []

    def send(self, request: ClientHttpRequest) -> ClientHttpResponse:
        self.requests.append(request)
        return self.response


def _response(release: LayeredReleaseIdentity) -> ClientHttpResponse:
    array_sections = {
        "tasks",
        "lanes",
        "agents",
        "approvals",
        "authority_leases",
        "publications",
    }
    core = {
        field: [] if field in array_sections else {}
        for field in FILE_WORKSPACE_CORE_SECTION_FIELDS
    }
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["failures"] = {"observations": []}
    core["tool_reflection"] = {
        "declared_tool_catalog_digest": release.declared_tool_catalog_digest,
        "capability_binding_digest": _digest("binding"),
        "affordance_snapshot_digest": _digest("affordance"),
        "available_tool_names": [],
        "affordances": [],
    }
    projection = FileWorkspacePublicV2(
        release=release,
        core=FileWorkspaceCoreProjectionV2(core),
        extensions=(),
    )
    binding_digest = _digest("binding")
    affordance_digest = _digest("affordance")
    return ClientHttpResponse(
        status_code=200,
        media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        body=json.dumps(projection.to_dict()).encode("utf-8"),
        headers={
            "OpenZyme-Workspace-Contract": FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION,
            "OpenZyme-Release-Digest": release.release_digest,
            "OpenZyme-Public-Contract-Digest": (
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
            ),
            "OpenZyme-Projection-Digest": projection.projection_digest,
            "OpenZyme-Capability-Binding-Digest": binding_digest,
            "OpenZyme-Affordance-Snapshot-Digest": affordance_digest,
        },
    )


def test_client_verifies_exact_v2_before_sending_mutation() -> None:
    release = _release()
    inspection_response = _response(release)
    transport = _Transport(inspection_response)
    client = OpenZymeV2Client(transport=transport, expected_release=release)

    projection, verified = client.inspect_workspace(
        session_id="session-1",
        authorization="Bearer private",
    )
    assert projection.release == release
    assert transport.requests[0].headers["Accept"] == (
        FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
    )

    transport.response = ClientHttpResponse(
        status_code=202,
        media_type="application/json",
        body=b"{}",
        headers=inspection_response.headers,
    )
    response = client.send_mutation(
        method="POST",
        path="/v3/sessions/session-1/messages",
        authorization="Bearer private",
        idempotency_key="message-1",
        body=b'{"content":"hello"}',
        verified_contract=verified,
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_digest=_digest("affordance"),
    )
    assert response.status_code == 202
    assert transport.requests[-1].headers["OpenZyme-Release-Digest"] == (
        release.release_digest
    )


def test_client_bootstraps_session_against_release_without_projection_identity() -> None:
    release = _release()
    transport = _Transport(
        ClientHttpResponse(
            status_code=200,
            media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
            body=b'{"operation":"session.bootstrap"}',
            headers={
                "OpenZyme-Workspace-Contract": (
                    FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                ),
                "OpenZyme-Release-Digest": release.release_digest,
                "OpenZyme-Public-Contract-Digest": (
                    FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                ),
            },
        )
    )
    client = OpenZymeV2Client(transport=transport, expected_release=release)

    response = client.bootstrap_session(
        authorization="Bearer operator",
        idempotency_key="bootstrap-session-1",
        body=b'{"session_id":"session-1"}',
    )

    assert response.status_code == 200
    request = transport.requests[0]
    assert (request.method, request.path) == ("POST", "/v3/sessions")
    assert request.headers["OpenZyme-Release-Digest"] == release.release_digest
    assert "OpenZyme-Projection-Digest" not in request.headers


def test_client_rejects_mutation_response_identity_drift() -> None:
    release = _release()
    inspection_response = _response(release)
    transport = _Transport(inspection_response)
    client = OpenZymeV2Client(transport=transport, expected_release=release)
    _, verified = client.inspect_workspace(
        session_id="session-1",
        authorization="Bearer private",
    )
    stale_headers = dict(inspection_response.headers)
    stale_headers["OpenZyme-Projection-Digest"] = _digest("stale")
    transport.response = ClientHttpResponse(
        status_code=200,
        media_type="application/json",
        body=b"{}",
        headers=stale_headers,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.send_mutation(
            method="POST",
            path="/v3/sessions/session-1/messages",
            authorization="Bearer private",
            idempotency_key="message-1",
            body=b"{}",
            verified_contract=verified,
            capability_binding_digest=verified.capability_binding_digest,
            affordance_snapshot_digest=verified.affordance_snapshot_digest,
        )

    assert rejected.value.code == "client_mutation_response_identity_mismatch"
    assert rejected.value.mutation_applied is None
    assert rejected.value.effect_certainty == "dispatch_in_doubt"
    assert rejected.value.fallback_performed is False


def test_client_rejects_release_drift_before_mutation_transport() -> None:
    release = _release()
    transport = _Transport(_response(release))
    client = OpenZymeV2Client(transport=transport, expected_release=release)
    stale = VerifiedServerContract(
        release_digest=_digest("stale"),
        public_contract_digest=_digest("contract"),
        projection_digest=_digest("projection"),
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_digest=_digest("affordance"),
    )

    with pytest.raises(OpenZymeClientContractError) as error:
        client.send_mutation(
            method="POST",
            path="/v3/sessions/session-1/messages",
            authorization="Bearer private",
            idempotency_key="message-1",
            body=b"{}",
            verified_contract=stale,
            capability_binding_digest=_digest("binding"),
            affordance_snapshot_digest=_digest("affordance"),
        )

    assert error.value.code == "client_release_identity_stale"
    assert error.value.mutation_applied is False
    assert transport.requests == []


@pytest.mark.parametrize(
    ("field_name", "error_code"),
    [
        ("capability_binding_digest", "client_capability_binding_stale"),
        ("affordance_snapshot_digest", "client_affordance_snapshot_stale"),
    ],
)
def test_client_rejects_binding_or_affordance_drift_before_transport(
    field_name: str,
    error_code: str,
) -> None:
    release = _release()
    transport = _Transport(_response(release))
    client = OpenZymeV2Client(transport=transport, expected_release=release)
    _, verified = client.inspect_workspace(
        session_id="session-1",
        authorization="Bearer private",
    )
    request_count = len(transport.requests)
    identities = {
        "capability_binding_digest": verified.capability_binding_digest,
        "affordance_snapshot_digest": verified.affordance_snapshot_digest,
    }
    identities[field_name] = _digest("stale")

    with pytest.raises(OpenZymeClientContractError) as error:
        client.send_mutation(
            method="POST",
            path="/v3/sessions/session-1/messages",
            authorization="Bearer private",
            idempotency_key="message-1",
            body=b"{}",
            verified_contract=verified,
            **identities,
        )

    assert error.value.code == error_code
    assert len(transport.requests) == request_count


def test_client_rejects_unknown_root_and_media_type() -> None:
    release = _release()
    response = _response(release)
    transport = _Transport(
        ClientHttpResponse(
            status_code=200,
            media_type="application/json",
            body=response.body,
            headers=response.headers,
        )
    )
    client = OpenZymeV2Client(transport=transport, expected_release=release)
    with pytest.raises(OpenZymeClientContractError) as media:
        client.inspect_workspace(
            session_id="session-1",
            authorization="Bearer private",
        )
    assert media.value.code == "client_workspace_media_type_mismatch"

    payload = json.loads(response.body)
    payload["scientific_attempts"] = []
    transport.response = ClientHttpResponse(
        status_code=200,
        media_type=FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        body=json.dumps(payload).encode("utf-8"),
        headers=response.headers,
    )
    with pytest.raises(OpenZymeClientContractError) as closed:
        client.inspect_workspace(
            session_id="session-1",
            authorization="Bearer private",
        )
    assert closed.value.code == "client_workspace_payload_invalid"


@pytest.mark.parametrize(
    "header_name",
    [
        "OpenZyme-Workspace-Contract",
        "OpenZyme-Release-Digest",
        "OpenZyme-Public-Contract-Digest",
        "OpenZyme-Projection-Digest",
        "OpenZyme-Capability-Binding-Digest",
        "OpenZyme-Affordance-Snapshot-Digest",
    ],
)
def test_client_rejects_response_header_identity_drift(
    header_name: str,
) -> None:
    release = _release()
    response = _response(release)
    headers = dict(response.headers)
    headers[header_name] = _digest(f"stale:{header_name}")
    transport = _Transport(
        ClientHttpResponse(
            status_code=response.status_code,
            media_type=response.media_type,
            body=response.body,
            headers=headers,
        )
    )
    client = OpenZymeV2Client(transport=transport, expected_release=release)

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.inspect_workspace(
            session_id="session-1",
            authorization="Bearer private",
        )

    assert rejected.value.code == "client_response_identity_mismatch"
    assert rejected.value.mutation_applied is False
    assert rejected.value.fallback_performed is False
