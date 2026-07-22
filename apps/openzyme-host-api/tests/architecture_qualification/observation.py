from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import (
    canonical_json_document_bytes,
)

from .composition import ProductionComposition
from .execution_evidence import record_observation_evidence


OBSERVATION_SCHEMA_ID = "openzyme_v3_architecture_observation@1"
OFFLINE_OBSERVATION_RECEIPT_SCHEMA_ID = (
    "openzyme_v3_architecture_offline_observation_receipt@1"
)
_OBSERVATION_FIELDS = frozenset(
    {
        "counts",
        "database",
        "effect_ledger",
        "generation",
        "profile_id",
        "public_projection",
        "roots",
        "schema_id",
        "workers",
    }
)
_VERSION_COLUMNS = frozenset(
    {
        "claim_epoch",
        "fence_epoch",
        "lease_epoch",
        "mutation_generation",
        "process_epoch",
        "state_version",
    }
)


class QualificationObservationError(RuntimeError):
    code = "architecture_qualification_observation_invalid"


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise QualificationObservationError("SQLite contains a non-finite value")
        return value
    if isinstance(value, bytes):
        return {"byte_length": len(value), "sha256": _sha256(value)}
    raise QualificationObservationError(
        f"SQLite contains unsupported value type {type(value).__name__!r}"
    )


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@dataclass(frozen=True, slots=True)
class ObservationCounts:
    state_version_total: int
    event_count: int
    row_count: int
    effect_count: int
    worker_tick_count: int
    notifier_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "effect_count": self.effect_count,
            "event_count": self.event_count,
            "notifier_count": self.notifier_count,
            "row_count": self.row_count,
            "state_version_total": self.state_version_total,
            "worker_tick_count": self.worker_tick_count,
        }


@dataclass(frozen=True, slots=True)
class QualificationObservation:
    payload: dict[str, object]
    observation_digest: str
    counts: ObservationCounts


@dataclass(frozen=True, slots=True)
class OfflineObservationReceipt:
    payload: Mapping[str, object]
    receipt_digest: str

    def to_dict(self) -> dict[str, object]:
        return {**dict(self.payload), "receipt_digest": self.receipt_digest}


def _database_snapshot(database_path: Path) -> tuple[dict[str, object], int, int, int]:
    if not database_path.is_file():
        raise QualificationObservationError("qualification SQLite database is absent")
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        table_names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables: list[dict[str, object]] = []
        state_version_total = 0
        event_count = 0
        row_count = 0
        for table_name in table_names:
            quoted_table = _quote_identifier(table_name)
            column_rows = list(connection.execute(f"PRAGMA table_info({quoted_table})"))
            columns = [str(row[1]) for row in column_rows]
            primary = [
                str(row[1])
                for row in sorted(column_rows, key=lambda item: int(item[5]))
                if int(row[5]) > 0
            ]
            order_columns = primary or columns
            order_sql = ", ".join(_quote_identifier(item) for item in order_columns)
            query = f"SELECT * FROM {quoted_table}"
            if order_sql:
                query += f" ORDER BY {order_sql}"
            rows = [
                {column: _json_value(row[column]) for column in columns}
                for row in connection.execute(query)
            ]
            row_count += len(rows)
            if "event" in table_name or "transition" in table_name:
                event_count += len(rows)
            for row in rows:
                for column, value in row.items():
                    if column in _VERSION_COLUMNS and isinstance(value, int):
                        state_version_total += value
            tables.append(
                {
                    "columns": columns,
                    "primary_key": primary,
                    "rows": rows,
                    "table": table_name,
                }
            )
        payload: dict[str, object] = {"tables": tables}
        return payload, state_version_total, event_count, row_count
    except sqlite3.Error as exc:
        raise QualificationObservationError(
            "qualification SQLite snapshot failed"
        ) from exc
    finally:
        connection.close()


def _file_root_snapshot(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise QualificationObservationError(
            f"qualification observation root {resolved} is absent"
        )
    files: list[dict[str, object]] = []
    for candidate in sorted(resolved.rglob("*")):
        if candidate.is_symlink():
            raise QualificationObservationError(
                f"qualification observation refuses symlink {candidate}"
            )
        if not candidate.is_file():
            continue
        content = candidate.read_bytes()
        files.append(
            {
                "byte_length": len(content),
                "path": candidate.relative_to(resolved).as_posix(),
                "sha256": _sha256(content),
            }
        )
    payload: dict[str, object] = {"files": files}
    return {**payload, "root_digest": _sha256(canonical_json_bytes(payload))}


def _parse_sse_events(body: str) -> list[object]:
    events: list[object] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            events.append(json.loads(line[5:].strip()))
        except json.JSONDecodeError as exc:
            raise QualificationObservationError(
                "public event projection returned invalid SSE JSON"
            ) from exc
    return events


def _public_projection(
    composition: ProductionComposition,
    *,
    session_ids: tuple[str, ...],
) -> dict[str, object]:
    client = composition.client
    if client is None:
        raise QualificationObservationError(
            "public projection requires an entered production composition"
        )
    sessions: list[dict[str, object]] = []
    for session_id in sorted(set(session_ids)):
        workspace = client.get(f"/v3/sessions/{session_id}/workspace")
        approvals = client.get(f"/v3/sessions/{session_id}/pending-approvals")
        events = client.get(
            f"/v3/sessions/{session_id}/events",
            params={"envelope": "true", "follow": "false", "replay": "true"},
        )
        responses = (workspace, approvals, events)
        if any(response.status_code != 200 for response in responses):
            raise QualificationObservationError(
                f"public projection failed for session {session_id!r}"
            )
        sessions.append(
            {
                "events": _parse_sse_events(events.text),
                "pending_approvals": approvals.json(),
                "session_id": session_id,
                "workspace": workspace.json(),
            }
        )
    return {"sessions": sessions}


def collect_observation(
    composition: ProductionComposition,
    *,
    session_ids: tuple[str, ...] = (),
) -> QualificationObservation:
    database, state_total, event_count, row_count = _database_snapshot(
        composition.roots.database_path
    )
    effect_ledger = composition.external_effect_ledger.snapshot()
    durable_status = composition.durable_supervisor.status()
    background_status = composition.background_runtime.status()
    notifier_count = (
        composition.dependencies.v3_signal_notifier.notify_count
        + composition.dependencies.v3_durable_work_notifier.notify_count
    )
    worker_tick_count = int(durable_status["tick_count"]) + int(
        background_status["tick_count"]
    )
    counts = ObservationCounts(
        state_version_total=state_total,
        event_count=event_count,
        row_count=row_count,
        effect_count=composition.external_effect_ledger.count_effects(),
        worker_tick_count=worker_tick_count,
        notifier_count=notifier_count,
    )
    roots = {
        "artifacts": _file_root_snapshot(composition.roots.artifact_root),
        "blobs": _file_root_snapshot(composition.roots.blob_root),
        "sandboxes": _file_root_snapshot(composition.roots.sandbox_root),
        "workspace_projections": _file_root_snapshot(composition.roots.workspace_root),
    }
    payload: dict[str, object] = {
        "counts": counts.to_dict(),
        "database": database,
        "effect_ledger": effect_ledger,
        "generation": composition.generation,
        "profile_id": "local_single_process_file_sqlite@1",
        "public_projection": _public_projection(
            composition,
            session_ids=session_ids,
        ),
        "roots": roots,
        "schema_id": OBSERVATION_SCHEMA_ID,
        "workers": {
            "background_runtime": background_status,
            "durable_supervisor": durable_status,
            "notifiers": {
                "durable_work": {
                    "last_session_id": composition.dependencies.v3_durable_work_notifier.last_notified_session_id,
                    "notify_count": composition.dependencies.v3_durable_work_notifier.notify_count,
                },
                "runtime": {
                    "last_session_id": composition.dependencies.v3_signal_notifier.last_notified_session_id,
                    "notify_count": composition.dependencies.v3_signal_notifier.notify_count,
                },
            },
        },
    }
    observation = QualificationObservation(
        payload=payload,
        observation_digest=_sha256(canonical_json_bytes(payload)),
        counts=counts,
    )
    record_observation_evidence(
        observation_digest=observation.observation_digest,
        effect_ledger=effect_ledger,
    )
    return observation


def find_private_projection_fields(
    value: object,
    *,
    forbidden_fields: frozenset[str],
) -> tuple[str, ...]:
    found: list[str] = []

    def visit(item: object, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key in forbidden_fields:
                    found.append(child_path)
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return tuple(found)


def _strict_canonical_observation(content: bytes) -> dict[str, object]:
    try:
        text = content.decode("utf-8")

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        payload = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QualificationObservationError(
            "offline observation is not strict JSON"
        ) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != _OBSERVATION_FIELDS
        or canonical_json_document_bytes(payload) != content
        or payload.get("schema_id") != OBSERVATION_SCHEMA_ID
    ):
        raise QualificationObservationError(
            "offline observation is not closed canonical JSON"
        )
    return payload


def _offline_table_rows(
    database: object,
    *,
    table_name: str,
) -> list[dict[str, object]]:
    if not isinstance(database, dict) or set(database) != {"tables"}:
        raise QualificationObservationError("offline database snapshot is invalid")
    tables = database["tables"]
    if not isinstance(tables, list):
        raise QualificationObservationError("offline database tables are invalid")
    for table in tables:
        if not isinstance(table, dict) or set(table) != {
            "columns",
            "primary_key",
            "rows",
            "table",
        }:
            raise QualificationObservationError(
                "offline database table is not closed"
            )
        if table.get("table") != table_name:
            continue
        rows = table.get("rows")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise QualificationObservationError("offline database rows are invalid")
        return [dict(row) for row in rows]
    raise QualificationObservationError(
        f"offline database table {table_name!r} is absent"
    )


def verify_observation_offline(
    content: bytes,
    *,
    expected_observation_digest: str,
) -> OfflineObservationReceipt:
    """Verify captured state/effect/root/public identity without a live Host."""

    payload = _strict_canonical_observation(content)
    observation_digest = _sha256(canonical_json_bytes(payload))
    if observation_digest != expected_observation_digest:
        raise QualificationObservationError(
            "offline observation digest differs from the captured identity"
        )
    raw_roots = payload.get("roots")
    if not isinstance(raw_roots, dict) or not raw_roots:
        raise QualificationObservationError("offline observation roots are invalid")
    root_digests: dict[str, str] = {}
    root_file_digests: set[str] = set()
    for root_name, raw_root in sorted(raw_roots.items()):
        if not isinstance(raw_root, dict) or set(raw_root) != {
            "files",
            "root_digest",
        }:
            raise QualificationObservationError(
                f"offline root {root_name!r} is not closed"
            )
        files = raw_root["files"]
        if not isinstance(files, list) or any(
            not isinstance(item, dict)
            or set(item) != {"byte_length", "path", "sha256"}
            for item in files
        ):
            raise QualificationObservationError(
                f"offline root {root_name!r} file manifest is invalid"
            )
        expected_root_digest = _sha256(canonical_json_bytes({"files": files}))
        if raw_root["root_digest"] != expected_root_digest:
            raise QualificationObservationError(
                f"offline root {root_name!r} digest mismatch"
            )
        root_digests[str(root_name)] = expected_root_digest
        root_file_digests.update(str(item["sha256"]) for item in files)

    effect_ledger = payload.get("effect_ledger")
    if not isinstance(effect_ledger, dict) or "ledger_digest" not in effect_ledger:
        raise QualificationObservationError("offline effect ledger is invalid")
    effect_material = {
        key: value for key, value in effect_ledger.items() if key != "ledger_digest"
    }
    effect_ledger_digest = _sha256(canonical_json_bytes(effect_material))
    if effect_ledger["ledger_digest"] != effect_ledger_digest:
        raise QualificationObservationError("offline effect ledger digest mismatch")

    artifact_rows = _offline_table_rows(
        payload.get("database"),
        table_name="session_artifact_records",
    )
    catalog_digests: set[str] = set()
    for row in artifact_rows:
        metadata_text = row.get("metadata_json")
        if not isinstance(metadata_text, str):
            raise QualificationObservationError(
                "offline artifact catalog metadata is not serialized JSON"
            )
        try:
            metadata = json.loads(metadata_text)
        except json.JSONDecodeError as exc:
            raise QualificationObservationError(
                "offline artifact catalog metadata is invalid"
            ) from exc
        if not isinstance(metadata, dict):
            raise QualificationObservationError(
                "offline artifact catalog metadata is not an object"
            )
        for key in ("content_digest", "sealed_digest"):
            digest = metadata.get(key)
            if digest is None:
                continue
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise QualificationObservationError(
                    "offline artifact catalog digest is invalid"
                )
            catalog_digests.add(digest)
            if digest not in root_file_digests:
                raise QualificationObservationError(
                    "offline artifact catalog digest has no captured bytes"
                )

    public_projection = payload.get("public_projection")
    if not isinstance(public_projection, dict) or set(public_projection) != {
        "sessions"
    }:
        raise QualificationObservationError("offline public projection is invalid")
    sessions = public_projection["sessions"]
    if not isinstance(sessions, list):
        raise QualificationObservationError(
            "offline public projection sessions are invalid"
        )
    public_artifact_count = 0
    for session in sessions:
        if not isinstance(session, dict):
            raise QualificationObservationError(
                "offline public session projection is invalid"
            )
        workspace = session.get("workspace")
        if not isinstance(workspace, dict):
            raise QualificationObservationError(
                "offline public workspace projection is invalid"
            )
        scientific = workspace.get("scientific_evidence")
        if not isinstance(scientific, dict):
            raise QualificationObservationError(
                "offline scientific evidence projection is invalid"
            )
        artifacts = scientific.get("artifacts")
        if not isinstance(artifacts, list):
            raise QualificationObservationError(
                "offline public artifact projection is invalid"
            )
        public_artifact_count += len(artifacts)
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise QualificationObservationError(
                    "offline public artifact is invalid"
                )
            digest = artifact.get("sealed_digest")
            if digest is None:
                continue
            if digest not in catalog_digests or digest not in root_file_digests:
                raise QualificationObservationError(
                    "offline public artifact digest does not close catalog bytes"
                )
    if not catalog_digests or public_artifact_count == 0:
        raise QualificationObservationError(
            "offline observation contains no byte-backed public evidence"
        )
    receipt_payload: dict[str, object] = {
        "artifact_digest_count": len(catalog_digests),
        "database_digest": _sha256(canonical_json_bytes(payload["database"])),
        "effect_ledger_digest": effect_ledger_digest,
        "observation_digest": observation_digest,
        "public_artifact_count": public_artifact_count,
        "public_projection_digest": _sha256(
            canonical_json_bytes(public_projection)
        ),
        "root_digests": root_digests,
        "schema_id": OFFLINE_OBSERVATION_RECEIPT_SCHEMA_ID,
    }
    return OfflineObservationReceipt(
        payload=receipt_payload,
        receipt_digest=_sha256(canonical_json_bytes(receipt_payload)),
    )


__all__ = [
    "OBSERVATION_SCHEMA_ID",
    "OFFLINE_OBSERVATION_RECEIPT_SCHEMA_ID",
    "OfflineObservationReceipt",
    "ObservationCounts",
    "QualificationObservation",
    "QualificationObservationError",
    "collect_observation",
    "find_private_projection_fields",
    "verify_observation_offline",
]
