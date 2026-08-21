"""Read-only closure proof for persisted Session composition state."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Any

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import canonical_sha256_digest

from .deployment_proof import SQLiteDeploymentProofError


@dataclass(frozen=True, slots=True)
class SessionCompositionStateProof:
    activation_epoch_id: str
    verified_session_count: int
    verified_binding_revision_count: int
    verified_inventory_binding_count: int
    pin_set_digest: str
    binding_set_digest: str
    inventory_reference_set_digest: str
    mutation_applied: bool = False
    plugin_import_performed: bool = False
    writer_enabled: bool = False

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_session_composition_state_proof@1",
            "activation_epoch_id": self.activation_epoch_id,
            "verified_session_count": self.verified_session_count,
            "verified_binding_revision_count": self.verified_binding_revision_count,
            "verified_inventory_binding_count": self.verified_inventory_binding_count,
            "pin_set_digest": self.pin_set_digest,
            "binding_set_digest": self.binding_set_digest,
            "inventory_reference_set_digest": self.inventory_reference_set_digest,
            "mutation_applied": self.mutation_applied,
            "plugin_import_performed": self.plugin_import_performed,
            "writer_enabled": self.writer_enabled,
        }


def verify_session_composition_state_read_only(
    connection: sqlite3.Connection,
    *,
    activation_epoch: DeploymentActivationEpoch,
) -> SessionCompositionStateProof:
    """Verify every Session pin, binding revision and adopted inventory reference."""

    initial_changes = connection.total_changes
    initial_transaction = connection.in_transaction
    try:
        pin_rows = connection.execute(
            """
            SELECT pin_id, session_id, deployment_epoch_id,
                   deployment_activation_digest, distribution_id,
                   composition_bundle_digest, release_digest, pin_digest, pin_json
            FROM openzyme_store_session_composition_pins
            ORDER BY session_id
            """
        ).fetchall()
        pin_digests: list[str] = []
        binding_digests: list[str] = []
        inventory_refs: list[dict[str, object]] = []
        for row in pin_rows:
            (
                pin_id,
                session_id,
                epoch_id,
                activation_digest,
                distribution_id,
                composition_bundle_digest,
                release_digest,
                pin_digest,
                pin_json,
            ) = (str(value) for value in row)
            payload = _json_object(pin_json, phase="session_pin_json")
            _verify_embedded_digest(payload, digest_field="pin_digest", phase="session_pin")
            expected_columns = {
                "pin_id": pin_id,
                "session_id": session_id,
                "deployment_epoch_id": epoch_id,
                "deployment_activation_digest": activation_digest,
                "distribution_id": distribution_id,
                "composition_bundle_digest": composition_bundle_digest,
                "release_digest": release_digest,
                "pin_digest": pin_digest,
            }
            observed_columns = {
                "pin_id": payload.get("pin_id"),
                "session_id": payload.get("session_id"),
                "deployment_epoch_id": payload.get("deployment_epoch_id"),
                "deployment_activation_digest": payload.get(
                    "deployment_activation_digest"
                ),
                "distribution_id": payload.get("distribution_id"),
                "composition_bundle_digest": payload.get("composition_bundle_digest"),
                "release_digest": canonical_sha256_digest(
                    payload.get("release_identity")
                ),
                "pin_digest": payload.get("pin_digest"),
            }
            if expected_columns != observed_columns:
                raise _error(
                    "Session composition pin columns differ from its payload",
                    "session_pin_columns",
                    expected=expected_columns,
                    observed=observed_columns,
                )
            expected_epoch = {
                "deployment_epoch_id": activation_epoch.epoch_id,
                "deployment_activation_digest": activation_epoch.activation_digest,
                "distribution_id": activation_epoch.distribution_id,
                "composition_bundle_digest": activation_epoch.composition_bundle_digest,
                "release_identity": activation_epoch.release_identity.to_dict(),
                "driver_bundle_digest": activation_epoch.driver_bundle_digest,
                "http_route_catalog_digest": (
                    activation_epoch.http_route_catalog_digest
                ),
                "contribution_catalogs_digest": (
                    activation_epoch.contribution_catalogs_digest
                ),
            }
            observed_epoch = {key: payload.get(key) for key in expected_epoch}
            if observed_epoch != expected_epoch:
                raise _error(
                    "Session composition pin does not bind the active epoch",
                    "session_pin_epoch",
                    expected=expected_epoch,
                    observed=observed_epoch,
                )
            rows = connection.execute(
                """
                SELECT binding_id, revision, extension_bundle_digest,
                       route_catalog_digest, binding_digest, binding_json
                FROM openzyme_store_session_capability_binding_revisions
                WHERE session_id = ?
                ORDER BY revision
                """,
                (session_id,),
            ).fetchall()
            _verify_binding_revisions(
                connection,
                rows=rows,
                session_id=session_id,
                pin_payload=payload,
                activation_epoch=activation_epoch,
                binding_digests=binding_digests,
                inventory_refs=inventory_refs,
            )
            pin_digests.append(pin_digest)
        orphan_sessions = connection.execute(
            """
            SELECT DISTINCT b.session_id
            FROM openzyme_store_session_capability_binding_revisions AS b
            LEFT JOIN openzyme_store_session_composition_pins AS p
              ON p.session_id = b.session_id
            WHERE p.session_id IS NULL
            ORDER BY b.session_id
            """
        ).fetchall()
        if orphan_sessions:
            raise _error(
                "capability binding exists without a Session composition pin",
                "session_binding_orphan",
                expected=(),
                observed=tuple(str(row[0]) for row in orphan_sessions),
            )
        return SessionCompositionStateProof(
            activation_epoch_id=activation_epoch.epoch_id,
            verified_session_count=len(pin_digests),
            verified_binding_revision_count=len(binding_digests),
            verified_inventory_binding_count=len(inventory_refs),
            pin_set_digest=canonical_sha256_digest(tuple(pin_digests)),
            binding_set_digest=canonical_sha256_digest(tuple(binding_digests)),
            inventory_reference_set_digest=canonical_sha256_digest(inventory_refs),
        )
    finally:
        if (
            connection.total_changes != initial_changes
            or connection.in_transaction != initial_transaction
        ):
            raise RuntimeError("Session composition verifier violated zero-mutation")


def _verify_binding_revisions(
    connection: sqlite3.Connection,
    *,
    rows: list[tuple[object, ...]],
    session_id: str,
    pin_payload: dict[str, Any],
    activation_epoch: DeploymentActivationEpoch,
    binding_digests: list[str],
    inventory_refs: list[dict[str, object]],
) -> None:
    if not rows:
        raise _error(
            "Session composition pin has no capability binding",
            "session_binding_missing",
            expected=pin_payload.get("initial_capability_binding_id"),
            observed=None,
        )
    observed_revisions = tuple(int(row[1]) for row in rows)
    expected_revisions = tuple(range(1, len(rows) + 1))
    if observed_revisions != expected_revisions:
        raise _error(
            "Session capability binding revisions are not contiguous",
            "session_binding_revision",
            expected=expected_revisions,
            observed=observed_revisions,
        )
    for row in rows:
        binding_id = str(row[0])
        revision = int(row[1])
        extension_bundle_digest = str(row[2])
        route_catalog_digest = str(row[3])
        binding_digest = str(row[4])
        payload = _json_object(str(row[5]), phase="session_binding_json")
        _verify_embedded_digest(
            payload,
            digest_field="binding_digest",
            phase="session_binding",
        )
        expected_columns = {
            "binding_id": binding_id,
            "session_id": session_id,
            "revision": revision,
            "extension_bundle_digest": extension_bundle_digest,
            "route_catalog_digest": route_catalog_digest,
            "binding_digest": binding_digest,
        }
        observed_columns = {key: payload.get(key) for key in expected_columns}
        if expected_columns != observed_columns:
            raise _error(
                "Session capability binding columns differ from its payload",
                "session_binding_columns",
                expected=expected_columns,
                observed=observed_columns,
            )
        if (
            extension_bundle_digest
            != activation_epoch.release_identity.extension_bundle_digest
            or route_catalog_digest
            != activation_epoch.release_identity.route_catalog_digest
        ):
            raise _error(
                "Session capability binding hot-swapped its pinned catalogs",
                "session_binding_catalog",
                expected={
                    "extension_bundle_digest": (
                        activation_epoch.release_identity.extension_bundle_digest
                    ),
                    "route_catalog_digest": (
                        activation_epoch.release_identity.route_catalog_digest
                    ),
                },
                observed={
                    "extension_bundle_digest": extension_bundle_digest,
                    "route_catalog_digest": route_catalog_digest,
                },
            )
        if revision == 1 and (
            binding_id != pin_payload.get("initial_capability_binding_id")
            or binding_digest != pin_payload.get("initial_capability_binding_digest")
            or pin_payload.get("initial_capability_binding_revision") != 1
        ):
            raise _error(
                "Session pin does not bind capability revision one",
                "session_initial_binding",
                expected={
                    "binding_id": binding_id,
                    "binding_digest": binding_digest,
                    "revision": 1,
                },
                observed={
                    "binding_id": pin_payload.get("initial_capability_binding_id"),
                    "binding_digest": pin_payload.get(
                        "initial_capability_binding_digest"
                    ),
                    "revision": pin_payload.get("initial_capability_binding_revision"),
                },
            )
        raw_inventory = payload.get("inventory_bindings")
        if not isinstance(raw_inventory, list):
            raise _error(
                "Session capability inventory binding list is invalid",
                "session_inventory_binding",
                expected="list",
                observed=type(raw_inventory).__name__,
            )
        for item in raw_inventory:
            if not isinstance(item, dict):
                raise _error(
                    "Session capability inventory binding is invalid",
                    "session_inventory_binding",
                    expected="object",
                    observed=type(item).__name__,
                )
            target_id = str(item.get("target_id"))
            generation = item.get("inventory_generation")
            inventory_digest = str(item.get("inventory_digest"))
            fact_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM openzyme_store_resource_capability_fact_records
                WHERE target_id = ? AND inventory_generation = ?
                  AND inventory_digest = ?
                """,
                (target_id, generation, inventory_digest),
            ).fetchone()[0]
            if int(fact_count) < 1:
                raise _error(
                    "Session binding references an absent target inventory",
                    "session_inventory_reference",
                    expected={
                        "target_id": target_id,
                        "inventory_generation": generation,
                        "inventory_digest": inventory_digest,
                    },
                    observed={"fact_count": int(fact_count)},
                )
            inventory_refs.append(
                {
                    "session_id": session_id,
                    "binding_revision": revision,
                    "target_id": target_id,
                    "inventory_generation": generation,
                    "inventory_digest": inventory_digest,
                }
            )
        binding_digests.append(binding_digest)


def _json_object(raw: str, *, phase: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _error(
            "stored composition JSON is invalid",
            phase,
            expected="JSON object",
            observed=exc.__class__.__name__,
        ) from exc
    if not isinstance(value, dict):
        raise _error(
            "stored composition JSON is not an object",
            phase,
            expected="object",
            observed=type(value).__name__,
        )
    return value


def _verify_embedded_digest(
    payload: dict[str, Any],
    *,
    digest_field: str,
    phase: str,
) -> None:
    observed = payload.get(digest_field)
    digest_payload = dict(payload)
    digest_payload.pop(digest_field, None)
    expected = canonical_sha256_digest(digest_payload)
    if observed != expected:
        raise _error(
            "stored composition object digest is invalid",
            phase,
            expected=expected,
            observed=observed,
        )


def _error(
    message: str,
    phase: str,
    *,
    expected: object = None,
    observed: object = None,
) -> SQLiteDeploymentProofError:
    return SQLiteDeploymentProofError(
        message,
        phase=phase,
        expected=expected,
        observed=observed,
        operator_action=(
            "keep every production surface closed and repair through the offline "
            "cutover workflow"
        ),
    )


__all__ = [
    "SessionCompositionStateProof",
    "verify_session_composition_state_read_only",
]
