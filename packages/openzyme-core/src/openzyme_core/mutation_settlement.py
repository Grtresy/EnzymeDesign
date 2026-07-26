from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import sqlite3

from openzyme_domain import MUTATION_SCOPE_SCHEMA_VERSION
from openzyme_domain import MUTATION_WRITER_SCHEMA_VERSION
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriterState

from .mutation_authority import HOST_MUTATION_COVERAGE_DIGEST
from .mutation_authority import HOST_MUTATION_POLICY_ID
from .mutation_authority import MAX_QUIESCENCE_SNAPSHOT_BYTES
from .mutation_authority import MAX_QUIESCENCE_SNAPSHOT_ROWS
from .mutation_authority import canonical_digest
from .mutation_authority import canonical_json_bytes


MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID = "mutation_authority_local_settlement@1"

_SCOPE_COLUMNS = (
    "scope_id",
    "schema_version",
    "scope_kind",
    "scope_ref",
    "parent_scope_id",
    "session_id",
    "state",
    "generation",
    "mutation_fencing_token",
    "state_version",
    "policy_id",
    "writer_coverage_manifest_digest",
    "sealed_receipt_digest",
)
_WRITER_COLUMNS = (
    "writer_id",
    "schema_version",
    "scope_id",
    "scope_generation",
    "owner_kind",
    "owner_ref",
    "process_epoch",
    "state",
    "parent_writer_id",
    "fencing_token",
    "state_version",
    "terminal_proof_digest",
)


class MutationLocalSettlementError(RuntimeError):
    retryable = False

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {
            "boundary": "mutation_authority_local_settlement",
            "disposition": "fail_closed",
            "blocker_code": code,
            **({} if details is None else dict(details)),
        }


@dataclass(frozen=True, slots=True)
class MutationLocalSettlementProjection:
    tables_present: bool
    nonterminal_scope_count: int
    active_writer_count: int
    scope_state_counts: dict[str, int]
    writer_state_counts: dict[str, int]
    observed_row_count: int
    snapshot_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_id": MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
            "tables_present": self.tables_present,
            "nonterminal_scope_count": self.nonterminal_scope_count,
            "active_writer_count": self.active_writer_count,
            "scope_state_counts": dict(self.scope_state_counts),
            "writer_state_counts": dict(self.writer_state_counts),
            "observed_row_count": self.observed_row_count,
            "snapshot_digest": self.snapshot_digest,
        }


def project_mutation_local_settlement(
    connection: sqlite3.Connection,
    *,
    max_rows: int = MAX_QUIESCENCE_SNAPSHOT_ROWS,
    max_bytes: int = MAX_QUIESCENCE_SNAPSHOT_BYTES,
) -> MutationLocalSettlementProjection:
    if (
        isinstance(max_rows, bool)
        or not isinstance(max_rows, int)
        or max_rows <= 0
        or max_rows > MAX_QUIESCENCE_SNAPSHOT_ROWS
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes <= 0
        or max_bytes > MAX_QUIESCENCE_SNAPSHOT_BYTES
    ):
        raise MutationLocalSettlementError(
            "mutation_settlement_bounds_invalid",
            "mutation settlement projection bounds are invalid",
        )
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    authority_tables = {
        "mutation_scope_records",
        "mutation_writer_records",
    }
    present = tables & authority_tables
    if present and present != authority_tables:
        raise MutationLocalSettlementError(
            "mutation_settlement_schema_incomplete",
            "mutation authority tables are incomplete",
        )
    if not present:
        return _build_projection(
            tables_present=False,
            scopes=[],
            writers=[],
            max_bytes=max_bytes,
        )

    scopes = _bounded_rows(
        connection,
        table_name="mutation_scope_records",
        columns=_SCOPE_COLUMNS,
        order_by="scope_id",
        limit=max_rows,
    )
    writers = _bounded_rows(
        connection,
        table_name="mutation_writer_records",
        columns=_WRITER_COLUMNS,
        order_by="writer_id",
        limit=max_rows - len(scopes),
    )
    _validate_scope_rows(scopes)
    _validate_writer_rows(writers, scope_ids={str(row["scope_id"]) for row in scopes})
    return _build_projection(
        tables_present=True,
        scopes=scopes,
        writers=writers,
        max_bytes=max_bytes,
    )


def _bounded_rows(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    columns: tuple[str, ...],
    order_by: str,
    limit: int,
) -> list[dict[str, object]]:
    if limit < 0:
        raise MutationLocalSettlementError(
            "mutation_settlement_row_limit_exceeded",
            "mutation settlement row limit was exceeded",
        )
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM {table_name} "
        f"ORDER BY {order_by} LIMIT ?",
        (limit + 1,),
    ).fetchall()
    if len(rows) > limit:
        raise MutationLocalSettlementError(
            "mutation_settlement_row_limit_exceeded",
            "mutation settlement row limit was exceeded",
        )
    return [
        {column: row[index] for index, column in enumerate(columns)}
        for row in rows
    ]


def _validate_scope_rows(scopes: list[dict[str, object]]) -> None:
    supported_states = {state.value for state in MutationScopeState}
    for scope in scopes:
        if (
            scope["schema_version"] != MUTATION_SCOPE_SCHEMA_VERSION
            or scope["policy_id"] != HOST_MUTATION_POLICY_ID
            or scope["writer_coverage_manifest_digest"]
            != HOST_MUTATION_COVERAGE_DIGEST
            or scope["state"] not in supported_states
            or not scope["session_id"]
        ):
            raise MutationLocalSettlementError(
                "mutation_settlement_scope_unsupported",
                "mutation settlement contains an unsupported scope",
            )


def _validate_writer_rows(
    writers: list[dict[str, object]],
    *,
    scope_ids: set[str],
) -> None:
    supported_states = {state.value for state in MutationWriterState}
    for writer in writers:
        if (
            writer["schema_version"] != MUTATION_WRITER_SCHEMA_VERSION
            or writer["state"] not in supported_states
            or str(writer["scope_id"]) not in scope_ids
        ):
            raise MutationLocalSettlementError(
                "mutation_settlement_writer_unsupported",
                "mutation settlement contains an unsupported writer",
            )


def _build_projection(
    *,
    tables_present: bool,
    scopes: list[dict[str, object]],
    writers: list[dict[str, object]],
    max_bytes: int,
) -> MutationLocalSettlementProjection:
    scope_state_counts = Counter(str(scope["state"]) for scope in scopes)
    writer_state_counts = Counter(str(writer["state"]) for writer in writers)
    nonterminal_scope_count = sum(
        count
        for state, count in scope_state_counts.items()
        if not MutationScopeState(state).is_terminal
    )
    active_writer_count = sum(
        count
        for state, count in writer_state_counts.items()
        if not MutationWriterState(state).is_terminal
    )
    snapshot = {
        "schema_id": MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
        "tables_present": tables_present,
        "scopes": scopes,
        "writers": writers,
    }
    if len(canonical_json_bytes(snapshot)) > max_bytes:
        raise MutationLocalSettlementError(
            "mutation_settlement_byte_limit_exceeded",
            "mutation settlement byte limit was exceeded",
        )
    if active_writer_count:
        raise MutationLocalSettlementError(
            "mutation_writers_active",
            "mutation settlement still contains active writers",
            details={"active_writer_count": active_writer_count},
        )
    return MutationLocalSettlementProjection(
        tables_present=tables_present,
        nonterminal_scope_count=nonterminal_scope_count,
        active_writer_count=active_writer_count,
        scope_state_counts=dict(sorted(scope_state_counts.items())),
        writer_state_counts=dict(sorted(writer_state_counts.items())),
        observed_row_count=len(scopes) + len(writers),
        snapshot_digest=canonical_digest(snapshot),
    )


__all__ = [
    "MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID",
    "MutationLocalSettlementError",
    "MutationLocalSettlementProjection",
    "project_mutation_local_settlement",
]
