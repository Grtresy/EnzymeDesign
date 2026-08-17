from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Callable
import re

from .repositories import CoreRepositories
from .repositories import _commit


class ScientificContractActivationError(RuntimeError):
    error_code = "scientific_contract_activation_rejected"


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED_PREREQUISITES = {
    "supersede-aox-hmm-" + "arti" + "fact-cutover": (
        "aox_legacy_superseded@1"
    ),
    "migrate-research-report-and-task-handoffs-to-files": (
        "revision_path_handoffs@1"
    ),
    "execute-hpc-jobs-from-workspace-revisions": (
        "workspace_revision_execution@1"
    ),
    "publish-and-sync-workspace-revisions": "workspace_publication@1",
    "support-git-lfs-work-products": "git_lfs_work_products@1",
}


def _require_digest(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ScientificContractActivationError(
            f"scientific contract activation requires an exact {field}"
        )


@dataclass(frozen=True, slots=True)
class ScientificPrerequisiteReceipt:
    change_id: str
    receipt_schema_id: str
    activated_contract_id: str
    source_revision: str
    schema_identity_digest: str
    contract_identity_digest: str
    transitive_receipt_digest: str
    receipt_digest: str
    accepted: bool
    superseded: bool

    def validate(self) -> None:
        expected = _REQUIRED_PREREQUISITES.get(self.change_id)
        if (
            expected is None
            or self.activated_contract_id != expected
            or not self.receipt_schema_id
            or not re.fullmatch(r"[0-9a-f]{40}", self.source_revision)
            or self.accepted is not True
            or self.superseded is True
        ):
            raise ScientificContractActivationError(
                f"scientific prerequisite receipt is not exact: {self.change_id}"
            )
        for name in (
            "schema_identity_digest",
            "contract_identity_digest",
            "transitive_receipt_digest",
            "receipt_digest",
        ):
            _require_digest(str(getattr(self, name)), name)


@dataclass(frozen=True, slots=True)
class LegacyAoxFreezeProof:
    supersession_receipt_digest: str
    frozen_inventory_digest: str
    legacy_decision: str
    runnable_campaign_count: int
    runnable_attempt_count: int
    active_authority_count: int
    mutable_selection_count: int
    unsettled_occurrence_count: int
    runnable_root_count: int
    current_deliverable_count: int
    active_continuation_count: int

    def validate(self) -> None:
        _require_digest(
            self.supersession_receipt_digest,
            "supersession_receipt_digest",
        )
        _require_digest(self.frozen_inventory_digest, "frozen_inventory_digest")
        counts = (
            self.runnable_campaign_count,
            self.runnable_attempt_count,
            self.active_authority_count,
            self.mutable_selection_count,
            self.unsettled_occurrence_count,
            self.runnable_root_count,
            self.current_deliverable_count,
            self.active_continuation_count,
        )
        if self.legacy_decision != "legacy_no_go" or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value != 0
            for value in counts
        ):
            raise ScientificContractActivationError(
                "legacy AOX authority is not completely frozen"
            )


@dataclass(frozen=True, slots=True)
class ScientificDependencyAvailability:
    publication_contract_digest: str
    git_lfs_contract_digest: str
    workspace_job_contract_digest: str
    revision_path_handoff_contract_digest: str
    current_incompatible_writer_enabled: bool
    provider_execution_requested: bool
    hpc_submission_requested: bool
    live_launch_requested: bool
    campaign_decision_requested: bool

    def validate(self) -> None:
        for name in (
            "publication_contract_digest",
            "git_lfs_contract_digest",
            "workspace_job_contract_digest",
            "revision_path_handoff_contract_digest",
        ):
            _require_digest(str(getattr(self, name)), name)
        if any(
            (
                self.current_incompatible_writer_enabled,
                self.provider_execution_requested,
                self.hpc_submission_requested,
                self.live_launch_requested,
                self.campaign_decision_requested,
            )
        ):
            raise ScientificContractActivationError(
                "scientific contract activation cannot carry writer, provider, HPC, live, or campaign effects"
            )


@dataclass(frozen=True, slots=True)
class ScientificContractActivationPreflight:
    contract_id: str
    contract_digest: str
    prerequisite_receipt_digest: str
    quiescence_receipt_digest: str
    prerequisite_receipts: tuple[ScientificPrerequisiteReceipt, ...]
    legacy_aox_freeze_proof: LegacyAoxFreezeProof
    dependency_availability: ScientificDependencyAvailability
    active_incompatible_writer_count: int
    active_scientific_process_count: int
    active_scientific_continuation_count: int
    unsettled_external_effect_count: int
    observed_at: str
    preflight_digest: str
    schema_version: str = "scientific_contract_activation_preflight@1"

    @classmethod
    def create(cls, **values: object) -> "ScientificContractActivationPreflight":
        payload = {
            "schema_version": "scientific_contract_activation_preflight@1",
            **{
                key: (
                    [asdict(item) for item in value]
                    if key == "prerequisite_receipts"
                    else asdict(value)
                    if key in {"legacy_aox_freeze_proof", "dependency_availability"}
                    else value
                )
                for key, value in values.items()
            },
        }
        return cls(**values, preflight_digest=_digest(payload))

    def require_quiescent(self) -> None:
        if self.contract_id != "scientific_file_deliverables@1":
            raise ScientificContractActivationError(
                "scientific contract activation targets an unsupported contract"
            )
        _require_digest(self.contract_digest, "contract_digest")
        _require_digest(
            self.prerequisite_receipt_digest,
            "prerequisite_receipt_digest",
        )
        _require_digest(
            self.quiescence_receipt_digest,
            "quiescence_receipt_digest",
        )
        receipts = {item.change_id: item for item in self.prerequisite_receipts}
        if (
            len(receipts) != len(self.prerequisite_receipts)
            or set(receipts) != set(_REQUIRED_PREREQUISITES)
        ):
            raise ScientificContractActivationError(
                "scientific prerequisite receipt set is incomplete"
            )
        for item in receipts.values():
            item.validate()
        prerequisite_digest = _digest(
            [
                asdict(receipts[change_id])
                for change_id in sorted(_REQUIRED_PREREQUISITES)
            ]
        )
        if prerequisite_digest != self.prerequisite_receipt_digest:
            raise ScientificContractActivationError(
                "scientific prerequisite receipt digest drifted"
            )
        self.legacy_aox_freeze_proof.validate()
        supersession = receipts[
            "supersede-aox-hmm-" + "arti" + "fact-cutover"
        ]
        if (
            self.legacy_aox_freeze_proof.supersession_receipt_digest
            != supersession.receipt_digest
        ):
            raise ScientificContractActivationError(
                "legacy AOX freeze proof does not bind the supersession receipt"
            )
        self.dependency_availability.validate()
        payload = asdict(self)
        payload.pop("preflight_digest")
        if self.preflight_digest != _digest(payload):
            raise ScientificContractActivationError(
                "scientific contract activation preflight digest drifted"
            )
        counts = (
            self.active_incompatible_writer_count,
            self.active_scientific_process_count,
            self.active_scientific_continuation_count,
            self.unsettled_external_effect_count,
        )
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value != 0
            for value in counts
        ):
            raise ScientificContractActivationError(
                "scientific contract activation requires zero legacy writers, "
                "processes, continuations, and unsettled effects"
            )


@dataclass(frozen=True, slots=True)
class ScientificContractEpoch:
    epoch: int
    contract_id: str
    contract_digest: str
    state: str
    scientific_file_writer_enabled: bool
    prerequisite_receipt_digest: str
    quiescence_receipt_digest: str
    activation_receipt_digest: str | None
    prepared_at: str
    activated_at: str | None


@dataclass(slots=True)
class ScientificContractEpochRepository:
    connection: sqlite3.Connection

    def prepare(
        self,
        preflight: ScientificContractActivationPreflight,
    ) -> ScientificContractEpoch:
        preflight.require_quiescent()
        existing = self.get_by_contract(
            preflight.contract_id,
            preflight.contract_digest,
        )
        if existing is not None:
            if (
                existing.prerequisite_receipt_digest
                == preflight.prerequisite_receipt_digest
                and existing.quiescence_receipt_digest
                == preflight.quiescence_receipt_digest
            ):
                return existing
            raise ScientificContractActivationError(
                "scientific contract epoch identity conflicts"
            )
        next_epoch = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(epoch), 0) + 1 FROM scientific_contract_epoch_records"
            ).fetchone()[0]
        )
        self.connection.execute(
            """
            INSERT INTO scientific_contract_epoch_records (
                epoch, contract_id, contract_digest, state,
                scientific_file_writer_enabled,
                prerequisite_receipt_digest, quiescence_receipt_digest,
                prepared_at
            ) VALUES (?, ?, ?, 'prepared', 0, ?, ?, ?)
            """,
            (
                next_epoch,
                preflight.contract_id,
                preflight.contract_digest,
                preflight.prerequisite_receipt_digest,
                preflight.quiescence_receipt_digest,
                preflight.observed_at,
            ),
        )
        _commit(self.connection)
        prepared = self.get(next_epoch)
        if prepared is None:
            raise ScientificContractActivationError(
                "prepared scientific contract epoch was not persisted"
            )
        return prepared

    def activate(
        self,
        *,
        epoch: int,
        activation_receipt_digest: str,
        activated_at: str,
    ) -> ScientificContractEpoch:
        current = self.get(epoch)
        if current is None:
            raise ScientificContractActivationError(
                "scientific contract epoch does not exist"
            )
        if current.state == "active":
            if current.activation_receipt_digest == activation_receipt_digest:
                return current
            raise ScientificContractActivationError(
                "scientific contract activation replay differs"
            )
        if current.state != "prepared" or self.get_active() is not None:
            raise ScientificContractActivationError(
                "scientific contract epoch cannot become active"
            )
        self.connection.execute(
            """
            UPDATE scientific_contract_epoch_records
            SET state = 'active', scientific_file_writer_enabled = 1,
                activation_receipt_digest = ?, activated_at = ?
            WHERE epoch = ? AND state = 'prepared'
            """,
            (activation_receipt_digest, activated_at, epoch),
        )
        _commit(self.connection)
        active = self.get(epoch)
        if active is None or active.state != "active":
            raise ScientificContractActivationError(
                "scientific contract epoch activation did not commit"
            )
        return active

    def get(self, epoch: int) -> ScientificContractEpoch | None:
        row = self.connection.execute(
            "SELECT * FROM scientific_contract_epoch_records WHERE epoch = ?",
            (epoch,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_active(self) -> ScientificContractEpoch | None:
        row = self.connection.execute(
            "SELECT * FROM scientific_contract_epoch_records WHERE state = 'active'"
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_contract(
        self,
        contract_id: str,
        contract_digest: str,
    ) -> ScientificContractEpoch | None:
        row = self.connection.execute(
            """
            SELECT * FROM scientific_contract_epoch_records
            WHERE contract_id = ? AND contract_digest = ?
            """,
            (contract_id, contract_digest),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificContractEpoch:
        return ScientificContractEpoch(
            epoch=int(row["epoch"]),
            contract_id=row["contract_id"],
            contract_digest=row["contract_digest"],
            state=row["state"],
            scientific_file_writer_enabled=bool(
                row["scientific_file_writer_enabled"]
            ),
            prerequisite_receipt_digest=row["prerequisite_receipt_digest"],
            quiescence_receipt_digest=row["quiescence_receipt_digest"],
            activation_receipt_digest=row["activation_receipt_digest"],
            prepared_at=row["prepared_at"],
            activated_at=row["activated_at"],
        )


@dataclass(slots=True)
class ScientificContractActivationService:
    repositories: CoreRepositories
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def activate(
        self,
        preflight: ScientificContractActivationPreflight,
    ) -> ScientificContractEpoch:
        preflight.require_quiescent()
        repository = ScientificContractEpochRepository(
            self.repositories.sessions.connection
        )
        with self.repositories.atomic(prefix="scientific_contract_activate"):
            prepared = repository.prepare(preflight)
            activation_receipt_digest = _digest(
                {
                    "schema_version": "scientific_contract_activation_receipt@1",
                    "epoch": prepared.epoch,
                    "contract_id": prepared.contract_id,
                    "contract_digest": prepared.contract_digest,
                    "preflight_digest": preflight.preflight_digest,
                    "prerequisite_receipt_digest": (
                        preflight.prerequisite_receipt_digest
                    ),
                    "quiescence_receipt_digest": preflight.quiescence_receipt_digest,
                }
            )
            return repository.activate(
                epoch=prepared.epoch,
                activation_receipt_digest=activation_receipt_digest,
                activated_at=self.now().isoformat(),
            )


__all__ = [
    "LegacyAoxFreezeProof",
    "ScientificDependencyAvailability",
    "ScientificPrerequisiteReceipt",
    "ScientificContractActivationError",
    "ScientificContractActivationPreflight",
    "ScientificContractActivationService",
    "ScientificContractEpoch",
    "ScientificContractEpochRepository",
]
