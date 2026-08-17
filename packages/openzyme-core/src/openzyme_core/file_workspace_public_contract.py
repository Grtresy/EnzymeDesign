from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping
from typing import Sequence

from openzyme_domain.control_plane import utc_now_iso
from openzyme_domain import FILE_WORKSPACE_PUBLIC_CONTRACT_ID

from .file_workspace_projection import file_workspace_public_schema_bundle_digest
from .repositories import CoreRepositories
from .tool_catalog import file_workspace_candidate_catalog_digest


FILE_WORKSPACE_PUBLIC_MEDIA_TYPE = (
    "application/vnd.openzyme.file-workspace+json;version=1"
)
REQUIRED_PREDECESSOR_CONTRACTS = {
    "migrate-scientific-deliverables-to-files": "scientific_file_deliverables@1",
    "replace-sandbox-" + "arti" + "fact-boundaries-with-files": "file_workspace_internal@1",
}


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_digest(value: str, *, field: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise FileWorkspacePublicContractError(
            "file_workspace_release_identity_invalid",
            f"{field} is not an exact sha256 digest",
        )


class FileWorkspacePublicContractError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PredecessorCompletionReceipt:
    change_id: str
    receipt_schema_id: str
    activated_contract_id: str
    source_revision: str
    schema_identity_digest: str
    contract_identity_digest: str
    activation_epoch: int
    transitive_receipt_digest: str
    receipt_digest: str
    accepted: bool
    superseded: bool = False

    def validate(self) -> None:
        expected = REQUIRED_PREDECESSOR_CONTRACTS.get(self.change_id)
        if (
            expected is None
            or self.activated_contract_id != expected
            or not self.receipt_schema_id
            or re.fullmatch(r"[0-9a-f]{40}", self.source_revision) is None
            or self.activation_epoch < 1
            or self.accepted is not True
            or self.superseded
        ):
            raise FileWorkspacePublicContractError(
                "file_workspace_predecessor_receipt_rejected",
                f"predecessor receipt {self.change_id!r} is not current and exact",
            )
        for name in (
            "schema_identity_digest",
            "contract_identity_digest",
            "transitive_receipt_digest",
            "receipt_digest",
        ):
            _require_digest(
                str(getattr(self, name)),
                field=f"{self.change_id}.{name}",
            )


@dataclass(frozen=True, slots=True)
class FileWorkspaceReleaseBundle:
    tool_catalog_digest: str
    executor_tool_catalog_digest: str
    schema_bundle_digest: str
    host_build_digest: str
    cli_build_digest: str
    sdk_build_digest: str
    ui_build_digest: str
    restore_schema_digest: str
    event_schema_digest: str
    contract_id: str = FILE_WORKSPACE_PUBLIC_CONTRACT_ID

    @classmethod
    def candidate(
        cls,
        *,
        host_build_digest: str,
        cli_build_digest: str,
        sdk_build_digest: str,
        ui_build_digest: str,
        restore_schema_digest: str,
        event_schema_digest: str,
    ) -> "FileWorkspaceReleaseBundle":
        return cls(
            tool_catalog_digest=file_workspace_candidate_catalog_digest(),
            executor_tool_catalog_digest=file_workspace_candidate_catalog_digest(
                executor=True
            ),
            schema_bundle_digest=file_workspace_public_schema_bundle_digest(),
            host_build_digest=host_build_digest,
            cli_build_digest=cli_build_digest,
            sdk_build_digest=sdk_build_digest,
            ui_build_digest=ui_build_digest,
            restore_schema_digest=restore_schema_digest,
            event_schema_digest=event_schema_digest,
        )

    def validate(self) -> None:
        if self.contract_id != FILE_WORKSPACE_PUBLIC_CONTRACT_ID:
            raise FileWorkspacePublicContractError(
                "file_workspace_contract_identity_invalid",
                "release bundle has the wrong public contract",
            )
        if self.tool_catalog_digest != file_workspace_candidate_catalog_digest():
            raise FileWorkspacePublicContractError(
                "file_workspace_tool_catalog_mismatch",
                "release bundle does not match the current Host tool catalog",
            )
        if self.executor_tool_catalog_digest != file_workspace_candidate_catalog_digest(
            executor=True
        ):
            raise FileWorkspacePublicContractError(
                "file_workspace_executor_tool_catalog_mismatch",
                "release bundle does not match the current executor tool catalog",
            )
        if self.schema_bundle_digest != file_workspace_public_schema_bundle_digest():
            raise FileWorkspacePublicContractError(
                "file_workspace_schema_bundle_mismatch",
                "release bundle does not match the current public schema bundle",
            )
        for name, value in self.to_dict().items():
            if name.endswith("_digest"):
                _require_digest(str(value), field=name)

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "tool_catalog_digest": self.tool_catalog_digest,
            "executor_tool_catalog_digest": self.executor_tool_catalog_digest,
            "schema_bundle_digest": self.schema_bundle_digest,
            "host_build_digest": self.host_build_digest,
            "cli_build_digest": self.cli_build_digest,
            "sdk_build_digest": self.sdk_build_digest,
            "ui_build_digest": self.ui_build_digest,
            "restore_schema_digest": self.restore_schema_digest,
            "event_schema_digest": self.event_schema_digest,
        }

    @property
    def bundle_digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class SessionContractDisposition:
    session_id: str
    disposition: str
    source_contract_id: str
    source_tool_catalog_digest: str
    source_schema_bundle_digest: str
    receipt_digest: str

    def validate_legacy(self) -> None:
        if self.disposition not in {"closed_historical", "unsupported_online"}:
            raise FileWorkspacePublicContractError(
                "file_workspace_session_disposition_invalid",
                f"existing session {self.session_id!r} lacks a closed legacy disposition",
            )
        if self.source_contract_id == FILE_WORKSPACE_PUBLIC_CONTRACT_ID:
            raise FileWorkspacePublicContractError(
                "file_workspace_session_disposition_invalid",
                "an unactivated current contract cannot be classified as legacy input",
            )
        for field, value in (
            ("source_tool_catalog_digest", self.source_tool_catalog_digest),
            ("source_schema_bundle_digest", self.source_schema_bundle_digest),
            ("receipt_digest", self.receipt_digest),
        ):
            _require_digest(value, field=field)


@dataclass(frozen=True, slots=True)
class FileWorkspaceActivationAdmission:
    quiescence_receipt_digest: str
    session_dispositions: tuple[SessionContractDisposition, ...]
    nonterminal_runtime_count: int
    pending_approval_count: int
    unknown_external_effect_count: int
    legacy_public_writer_counts: Mapping[str, int]
    release_bundle: FileWorkspaceReleaseBundle

    def validate(self, *, existing_session_ids: Sequence[str]) -> None:
        _require_digest(
            self.quiescence_receipt_digest,
            field="quiescence_receipt_digest",
        )
        self.release_bundle.validate()
        counters = {
            "nonterminal_runtime_count": self.nonterminal_runtime_count,
            "pending_approval_count": self.pending_approval_count,
            "unknown_external_effect_count": self.unknown_external_effect_count,
            **dict(self.legacy_public_writer_counts),
        }
        nonzero = {name: value for name, value in counters.items() if value != 0}
        if nonzero:
            raise FileWorkspacePublicContractError(
                "file_workspace_activation_not_quiescent",
                f"activation counters are not zero: {sorted(nonzero)}",
            )
        by_session = {item.session_id: item for item in self.session_dispositions}
        if len(by_session) != len(self.session_dispositions) or set(by_session) != set(
            existing_session_ids
        ):
            raise FileWorkspacePublicContractError(
                "file_workspace_session_inventory_incomplete",
                "activation requires one exact disposition for every existing session",
            )
        for item in by_session.values():
            item.validate_legacy()


class FileWorkspacePublicContractService:
    def __init__(self, repositories: CoreRepositories) -> None:
        self.repositories = repositories
        self.connection = repositories.sessions.connection

    def prepare(
        self,
        *,
        epoch: int,
        release_bundle: FileWorkspaceReleaseBundle,
        predecessor_receipts: Sequence[PredecessorCompletionReceipt],
        prepared_at: str | None = None,
    ) -> str:
        release_bundle.validate()
        by_change = {item.change_id: item for item in predecessor_receipts}
        if set(by_change) != set(REQUIRED_PREDECESSOR_CONTRACTS):
            raise FileWorkspacePublicContractError(
                "file_workspace_predecessor_receipt_incomplete",
                "both exact predecessor completion receipts are required",
            )
        for receipt in by_change.values():
            receipt.validate()
        predecessor_digest = _digest(
            [
                {
                    "change_id": item.change_id,
                    "receipt_schema_id": item.receipt_schema_id,
                    "activated_contract_id": item.activated_contract_id,
                    "source_revision": item.source_revision,
                    "schema_identity_digest": item.schema_identity_digest,
                    "contract_identity_digest": item.contract_identity_digest,
                    "activation_epoch": item.activation_epoch,
                    "transitive_receipt_digest": item.transitive_receipt_digest,
                    "receipt_digest": item.receipt_digest,
                    "accepted": item.accepted,
                    "superseded": item.superseded,
                }
                for item in sorted(predecessor_receipts, key=lambda value: value.change_id)
            ]
        )
        now = prepared_at or utc_now_iso()
        epoch_payload = {
            "epoch": epoch,
            **release_bundle.to_dict(),
            "predecessor_receipt_digest": predecessor_digest,
            "prepared_at": now,
        }
        epoch_digest = _digest(epoch_payload)
        with self.repositories.atomic(prefix="file_workspace_public_prepare"):
            self.connection.execute(
                """
                INSERT INTO file_workspace_public_epoch_records (
                    epoch, contract_id, state, tool_catalog_digest,
                    executor_tool_catalog_digest,
                    schema_bundle_digest, host_build_digest, cli_build_digest,
                    sdk_build_digest, ui_build_digest, restore_schema_digest,
                    event_schema_digest, predecessor_receipt_digest, prepared_at,
                    epoch_digest
                ) VALUES (?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    epoch,
                    release_bundle.contract_id,
                    release_bundle.tool_catalog_digest,
                    release_bundle.executor_tool_catalog_digest,
                    release_bundle.schema_bundle_digest,
                    release_bundle.host_build_digest,
                    release_bundle.cli_build_digest,
                    release_bundle.sdk_build_digest,
                    release_bundle.ui_build_digest,
                    release_bundle.restore_schema_digest,
                    release_bundle.event_schema_digest,
                    predecessor_digest,
                    now,
                    epoch_digest,
                ),
            )
        return epoch_digest

    def activate(
        self,
        *,
        epoch: int,
        admission: FileWorkspaceActivationAdmission,
        activated_at: str | None = None,
    ) -> str:
        session_ids = [
            str(row["session_id"])
            for row in self.connection.execute(
                "SELECT session_id FROM sessions ORDER BY session_id"
            ).fetchall()
        ]
        admission.validate(existing_session_ids=session_ids)
        row = self.connection.execute(
            "SELECT * FROM file_workspace_public_epoch_records WHERE epoch = ?",
            (epoch,),
        ).fetchone()
        if row is None or row["state"] != "prepared":
            raise FileWorkspacePublicContractError(
                "file_workspace_epoch_not_prepared",
                "the exact public epoch is not prepared",
            )
        active = self.connection.execute(
            """
            SELECT epoch FROM file_workspace_public_epoch_records
            WHERE state = 'active'
            """
        ).fetchone()
        if active is not None:
            raise FileWorkspacePublicContractError(
                "file_workspace_epoch_activation_conflict",
                "another file-workspace public epoch is already active",
            )
        for name, expected in admission.release_bundle.to_dict().items():
            column = "contract_id" if name == "contract_id" else name
            if row[column] != expected:
                raise FileWorkspacePublicContractError(
                    "file_workspace_release_bundle_mismatch",
                    f"prepared epoch differs at {name}",
                )
        now = activated_at or utc_now_iso()
        activation_payload = {
            "epoch": epoch,
            "epoch_digest": row["epoch_digest"],
            "release_bundle_digest": admission.release_bundle.bundle_digest,
            "quiescence_receipt_digest": admission.quiescence_receipt_digest,
            "session_disposition_receipts": sorted(
                item.receipt_digest for item in admission.session_dispositions
            ),
            "legacy_public_writer_counts": dict(
                sorted(admission.legacy_public_writer_counts.items())
            ),
            "activated_at": now,
        }
        activation_receipt_digest = _digest(activation_payload)
        with self.repositories.atomic(prefix="file_workspace_public_activate"):
            for item in admission.session_dispositions:
                self.connection.execute(
                    """
                    INSERT INTO file_workspace_session_contract_records (
                        session_id, public_epoch, contract_id, disposition,
                        tool_catalog_digest, schema_bundle_digest, mutation_allowed,
                        disposition_receipt_digest, classified_at
                    ) VALUES (?, NULL, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        item.session_id,
                        item.source_contract_id,
                        item.disposition,
                        item.source_tool_catalog_digest,
                        item.source_schema_bundle_digest,
                        item.receipt_digest,
                        now,
                    ),
                )
            self.connection.execute(
                """
                UPDATE file_workspace_public_epoch_records
                SET state = 'active', activation_receipt_digest = ?, activated_at = ?
                WHERE epoch = ? AND state = 'prepared'
                """,
                (activation_receipt_digest, now, epoch),
            )
            if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise FileWorkspacePublicContractError(
                    "file_workspace_epoch_activation_conflict",
                    "public epoch activation did not update exactly one prepared row",
                )
        return activation_receipt_digest

    def active_release_bundle(self) -> FileWorkspaceReleaseBundle:
        rows = self.connection.execute(
            """
            SELECT * FROM file_workspace_public_epoch_records
            WHERE state = 'active' AND contract_id = ?
            ORDER BY epoch
            """,
            (FILE_WORKSPACE_PUBLIC_CONTRACT_ID,),
        ).fetchall()
        if len(rows) != 1:
            raise FileWorkspacePublicContractError(
                "file_workspace_public_epoch_inactive",
                "exactly one active file-workspace public epoch is required",
            )
        row = rows[0]
        bundle = FileWorkspaceReleaseBundle(
            contract_id=str(row["contract_id"]),
            tool_catalog_digest=str(row["tool_catalog_digest"]),
            executor_tool_catalog_digest=str(row["executor_tool_catalog_digest"]),
            schema_bundle_digest=str(row["schema_bundle_digest"]),
            host_build_digest=str(row["host_build_digest"]),
            cli_build_digest=str(row["cli_build_digest"]),
            sdk_build_digest=str(row["sdk_build_digest"]),
            ui_build_digest=str(row["ui_build_digest"]),
            restore_schema_digest=str(row["restore_schema_digest"]),
            event_schema_digest=str(row["event_schema_digest"]),
        )
        bundle.validate()
        return bundle

    def require_request_release(
        self,
        *,
        contract_id: str | None,
        tool_catalog_digest: str | None,
        schema_bundle_digest: str | None,
        client_build_digest: str | None,
        executor: bool = False,
    ) -> FileWorkspaceReleaseBundle:
        bundle = self.active_release_bundle()
        expected_catalog_digest = (
            bundle.executor_tool_catalog_digest
            if executor
            else bundle.tool_catalog_digest
        )
        if (
            contract_id != bundle.contract_id
            or tool_catalog_digest != expected_catalog_digest
            or schema_bundle_digest != bundle.schema_bundle_digest
            or client_build_digest
            not in {
                bundle.cli_build_digest,
                bundle.sdk_build_digest,
                bundle.ui_build_digest,
            }
        ):
            raise FileWorkspacePublicContractError(
                "stale_file_workspace_contract",
                "request identity does not match the active release bundle",
            )
        return bundle

    def classify_new_session(self, session_id: str) -> None:
        bundle = self.active_release_bundle()
        row = self.connection.execute(
            """
            SELECT * FROM file_workspace_public_epoch_records
            WHERE state = 'active' AND contract_id = ?
            """,
            (bundle.contract_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - active_release_bundle closed this race
            raise FileWorkspacePublicContractError(
                "file_workspace_public_epoch_inactive",
                "new sessions require an active file-workspace public epoch",
            )
        receipt = _digest(
            {
                "session_id": session_id,
                "public_epoch": row["epoch"],
                "contract_id": row["contract_id"],
                "tool_catalog_digest": row["tool_catalog_digest"],
                "schema_bundle_digest": row["schema_bundle_digest"],
            }
        )
        existing = self.connection.execute(
            """
            SELECT * FROM file_workspace_session_contract_records
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        expected = (
            row["epoch"],
            row["contract_id"],
            row["tool_catalog_digest"],
            row["schema_bundle_digest"],
            receipt,
        )
        if existing is not None:
            observed = (
                existing["public_epoch"],
                existing["contract_id"],
                existing["tool_catalog_digest"],
                existing["schema_bundle_digest"],
                existing["disposition_receipt_digest"],
            )
            if (
                observed == expected
                and existing["disposition"] == "current"
                and existing["mutation_allowed"] == 1
            ):
                return
            raise FileWorkspacePublicContractError(
                "file_workspace_session_contract_conflict",
                "session already has a different public contract disposition",
            )
        self.connection.execute(
            """
            INSERT INTO file_workspace_session_contract_records (
                session_id, public_epoch, contract_id, disposition,
                tool_catalog_digest, schema_bundle_digest, mutation_allowed,
                disposition_receipt_digest, classified_at
            ) VALUES (?, ?, ?, 'current', ?, ?, 1, ?, ?)
            """,
            (
                session_id,
                row["epoch"],
                row["contract_id"],
                row["tool_catalog_digest"],
                row["schema_bundle_digest"],
                receipt,
                utc_now_iso(),
            ),
        )

    def require_current_session(self, session_id: str) -> None:
        row = self.connection.execute(
            """
            SELECT session_contract.*, epoch.state AS epoch_state
            FROM file_workspace_session_contract_records AS session_contract
            LEFT JOIN file_workspace_public_epoch_records AS epoch
              ON epoch.epoch = session_contract.public_epoch
            WHERE session_contract.session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if (
            row is None
            or row["disposition"] != "current"
            or row["mutation_allowed"] != 1
            or row["epoch_state"] != "active"
        ):
            raise FileWorkspacePublicContractError(
                "file_workspace_session_unsupported_online",
                "this session is historical or unsupported by the current runtime",
            )

    def current_session_ids(self) -> tuple[str, ...]:
        rows = self.connection.execute(
            """
            SELECT session_contract.session_id
            FROM file_workspace_session_contract_records AS session_contract
            JOIN file_workspace_public_epoch_records AS epoch
              ON epoch.epoch = session_contract.public_epoch
            WHERE session_contract.disposition = 'current'
              AND session_contract.mutation_allowed = 1
              AND epoch.state = 'active'
            ORDER BY session_contract.session_id
            """
        ).fetchall()
        return tuple(str(row["session_id"]) for row in rows)


__all__ = [
    "FILE_WORKSPACE_PUBLIC_CONTRACT_ID",
    "FILE_WORKSPACE_PUBLIC_MEDIA_TYPE",
    "REQUIRED_PREDECESSOR_CONTRACTS",
    "FileWorkspaceActivationAdmission",
    "FileWorkspacePublicContractError",
    "FileWorkspacePublicContractService",
    "FileWorkspaceReleaseBundle",
    "PredecessorCompletionReceipt",
    "SessionContractDisposition",
]
