from __future__ import annotations

import pytest

from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import canonical_sha256_digest


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def test_session_bootstrap_authorization_has_a_closed_round_trip() -> None:
    authorization = SessionBootstrapAuthorization.create(
        authorization_id="authorization-1",
        operator_actor_id="operator-1",
        project_id="project-1",
        session_id="session-1",
        root_authority_lease_digest=_digest("root-lease"),
        session_composition_pin_digest=_digest("composition-pin"),
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        repository_pin_digest=_digest("repository-pin"),
        workspace_generation=1,
        workspace_provisioning_intent_id="provisioning-intent-1",
        workspace_provisioning_intent_digest=_digest("provisioning-intent"),
        generation=1,
        fence=2,
        issued_at="2026-08-20T09:59:00+00:00",
        expires_at="2026-08-20T10:01:00+00:00",
    )

    assert SessionBootstrapAuthorization.from_dict(authorization.to_dict()) == (
        authorization
    )

    drifted = {**authorization.to_dict(), "ambient_authority": True}
    with pytest.raises(ValueError, match="closed schema"):
        SessionBootstrapAuthorization.from_dict(drifted)
