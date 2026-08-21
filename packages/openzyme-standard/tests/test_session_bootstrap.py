from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import sqlite3

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import json_compatible
from openzyme_kernel import SessionBootstrapCommand
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_store_sqlite import AgentAuthorityLeaseSQLiteKernelEntityCodec
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionCapabilityBindingSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionCompositionPinSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only
from openzyme_standard import build_standard_fresh_install_seed
from openzyme_standard import build_standard_kernel_public_projection_provider
from openzyme_standard import verify_standard_deployment_startup_read_only
from openzyme_standard.host_surface import (
    build_standard_file_workspace_v2_host_surface,
)


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


@dataclass(frozen=True)
class _Verifier:
    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision:
        assert now_iso == "2026-08-20T10:00:00+00:00"
        return SessionBootstrapAuthorityDecision(
            allowed=True,
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.authorization_digest,
        )


def test_plugin_free_sqlite_bootstrap_has_no_impossible_preseeded_lease() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=_digest("wheels"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
        epoch_id="epoch-1",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T09:58:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    store = SQLiteControlStore(
        connection,
        codecs=(
            AgentAuthorityLeaseSQLiteKernelEntityCodec(),
            AgentMemberSQLiteKernelEntityCodec(),
            SessionCapabilityBindingSQLiteKernelEntityCodec(),
            SessionCompositionPinSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
        ),
    )
    grant = AuthorityGrant.create(
        grant_id="root-grant-1",
        scope_id="session-1",
        operations=(
            "authority.lease.issue",
            "collaboration.create_task",
            "collaboration.register_agent",
        ),
        generation=1,
        fence=1,
    )
    lease = AgentAuthorityLease.create(
        lease_id="root-lease-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(grant,),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-20T10:00:00+00:00",
        expires_at=None,
        agent_id="master-1",
        policy_digest=_digest("root-policy"),
        idempotency_key="bootstrap-session-1",
        updated_at="2026-08-20T10:00:00+00:00",
    )
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=(
            seed.activation_epoch.release_identity.extension_bundle_digest
        ),
        route_catalog_digest=seed.activation_epoch.release_identity.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-20T10:00:00+00:00",
    )
    pin = SessionCompositionPin.create(
        pin_id="pin-1",
        session_id="session-1",
        deployment_epoch=seed.activation_epoch,
        initial_capability_binding_id=binding.binding_id,
        initial_capability_binding_revision=binding.revision,
        initial_capability_binding_digest=binding.binding_digest,
        created_by_actor_id="operator-1",
        created_at="2026-08-20T10:00:00+00:00",
    )
    authorization = SessionBootstrapAuthorization.create(
        authorization_id="operator-authorization-1",
        operator_actor_id="operator-1",
        project_id="project-1",
        session_id="session-1",
        root_authority_lease_digest=lease.lease_digest,
        session_composition_pin_digest=pin.pin_digest,
        extension_bundle_digest=binding.extension_bundle_digest,
        capability_binding_digest=binding.binding_digest,
        generation=1,
        fence=1,
        issued_at="2026-08-20T09:59:00+00:00",
        expires_at="2026-08-20T10:01:00+00:00",
    )
    command = SessionBootstrapCommand(
        command_id="command-bootstrap-session-1",
        idempotency_key="bootstrap-session-1",
        correlation_id="correlation-bootstrap-session-1",
        authorization=authorization,
        session_id="session-1",
        project_id="project-1",
        title="Standard qualification",
        objective="Prove atomic fresh Session authority",
        master_member_id="master-1",
        master_name="Master",
        root_authority_lease=lease,
        initial_capability_binding=binding,
        session_composition_pin=pin,
    )

    receipt = SessionBootstrapKernelApplicationService(
        store=store,
        clock=DeterministicClock(datetime(2026, 8, 20, 10, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
        authority_verifier=_Verifier(),
    ).bootstrap(command)

    assert receipt.mutation_applied is True
    assert store.read(entity_type="session", entity_id="session-1") is not None
    master = store.read(entity_type="agent_member", entity_id="master-1")
    assert master is not None
    assert master.payload["active_authority_lease_id"] == "root-lease-1"
    restored = store.read(
        entity_type="agent_authority_lease", entity_id="root-lease-1"
    )
    assert restored is not None
    assert restored.payload["lease_digest"] == lease.lease_digest
    restored_binding = store.read(
        entity_type="session_capability_binding_revision",
        entity_id=binding.binding_id,
    )
    assert restored_binding is not None
    assert restored_binding.payload["binding_digest"] == binding.binding_digest
    restored_pin = store.read(
        entity_type="session_composition_pin", entity_id=pin.pin_id
    )
    assert restored_pin is not None
    assert restored_pin.payload["pin_digest"] == pin.pin_digest
    assert connection.execute(
        "SELECT record_kind FROM agent_capability_lease_records"
    ).fetchone() == ("agent_authority_lease",)
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_outbox_records"
    ).fetchone() == (1,)

    startup = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=_digest("wheels"),
        verified_at="2026-08-20T10:00:01+00:00",
    )
    provider = build_standard_kernel_public_projection_provider(
        connection,
        startup=startup,
        clock=DeterministicClock(datetime(2026, 8, 20, 10, tzinfo=UTC)),
    )
    source = provider.inspect(
        session_id="session-1",
        actor_id="user:operator-1",
        correlation_id="projection-session-1",
    )

    assert source.context.session_id == "session-1"
    assert source.context.authority_lease_id == "root-lease-1"
    assert source.context.capability_binding_digest == binding.binding_digest
    assert source.core_payload["session"]["session_id"] == "session-1"
    assert source.core_payload["agents"][0]["agent_member_id"] == "master-1"
    assert source.core_payload["workspace"] == {
        "generations": [],
        "runtime_bindings": [],
        "repository_binding_pins": [],
        "checkpoints": [],
        "revision_path_verifications": [],
    }
    reflection = source.core_payload["tool_reflection"]
    assert reflection["capability_binding_digest"] == binding.binding_digest
    assert reflection["declared_tool_catalog_digest"] == (
        seed.activation_epoch.release_identity.declared_tool_catalog_digest
    )
    assert reflection["affordances"]

    surface = build_standard_file_workspace_v2_host_surface(
        connection,
        startup=startup,
        clock=DeterministicClock(datetime(2026, 8, 20, 10, tzinfo=UTC)),
    )
    projected = surface.inspect(
        session_id="session-1",
        actor_id="user:operator-1",
        correlation_id="host-projection-session-1",
    )
    assert projected.projection.extensions == ()
    assert projected.projection.core.to_dict() == json_compatible(source.core_payload)
    assert surface.activation_digest == seed.activation_epoch.activation_digest
